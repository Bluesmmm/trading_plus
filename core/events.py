"""
交易事件层（事实源）

所有交易相关操作都写入事件表，持仓从事件重建。
核心特性：幂等键、状态机、可重建性。
"""

from datetime import date, datetime
from hashlib import sha256
from typing import Optional
from uuid import UUID, uuid4

from core.types import Trade, TradeStatus, TradeType


class IdempotencyKey:
    """
    幂等键生成器

    格式：user_id:fund_code:type:date:amount:nav:client_msg_id
    保证相同交易不会重复创建
    """

    @staticmethod
    def generate(
        user_id: int,
        fund_code: str,
        trade_type: TradeType,
        trade_date: date,
        amount: Optional[float],
        nav_price: float,
        client_msg_id: Optional[str] = None,
    ) -> str:
        """生成幂等键"""
        parts = [
            str(user_id),
            fund_code,
            trade_type.value,
            trade_date.isoformat(),
            f"{amount:.2f}" if amount is not None else "None",
            f"{nav_price:.6f}",
            client_msg_id or "none",
        ]
        key_string = ":".join(parts)
        return sha256(key_string.encode()).hexdigest()


class TradeStateMachine:
    """
    交易状态机

    状态流转：created -> confirmed -> settled
    允许：created -> cancelled
    """

    _valid_transitions = {
        TradeStatus.CREATED: [TradeStatus.CONFIRMED, TradeStatus.CANCELLED, TradeStatus.FAILED],
        TradeStatus.CONFIRMED: [TradeStatus.SETTLED, TradeStatus.FAILED],
        TradeStatus.SETTLED: [],  # 终态
        TradeStatus.CANCELLED: [],  # 终态
        TradeStatus.FAILED: [],  # 终态
    }

    @classmethod
    def can_transition(cls, from_status: TradeStatus, to_status: TradeStatus) -> bool:
        """检查状态转换是否合法"""
        return to_status in cls._valid_transitions.get(from_status, [])

    @classmethod
    def transition(cls, trade: Trade, to_status: TradeStatus) -> Trade:
        """执行状态转换（返回新对象）"""
        if not cls.can_transition(trade.trade_status, to_status):
            raise ValueError(f"非法状态转换: {trade.trade_status} -> {to_status}")

        return Trade(
            **trade.model_dump(exclude={"trade_status", "updated_at"}),
            trade_status=to_status,
            updated_at=datetime.utcnow(),
        )


class PositionRebuilder:
    """
    持仓重建器

    从交易事件流重建持仓，确保可回放、可审计。
    """

    @staticmethod
    def rebuild(trades: list[Trade], as_of_date: date) -> dict[str, dict]:
        """
        从交易事件重建持仓

        返回：
        {
            "fund_code": {
                "shares": float,
                "avg_cost": float,
                "total_cost": float,
            }
        }
        """
        positions: dict[str, dict] = {}

        # 按 trade_date 排序
        sorted_trades = sorted(trades, key=lambda t: t.trade_date)

        for trade in sorted_trades:
            # 只处理已结算或已确认的交易
            if trade.trade_status not in (TradeStatus.SETTLED, TradeStatus.CONFIRMED):
                continue

            # 跳过 future trades
            if trade.trade_date > as_of_date:
                continue

            fund_code = trade.fund_code

            if fund_code not in positions:
                positions[fund_code] = {"shares": 0.0, "total_cost": 0.0}

            pos = positions[fund_code]

            if trade.trade_type == TradeType.BUY:
                # 买入：增加份额和成本
                if trade.amount is None:
                    continue
                shares = trade.amount / trade.nav_price
                pos["shares"] += shares
                pos["total_cost"] += trade.amount

            elif trade.trade_type == TradeType.SELL:
                # 卖出：减少份额，不改变平均成本
                if trade.shares is None:
                    continue
                pos["shares"] -= trade.shares
                # 成本按比例减少
                if pos["shares"] >= 0:
                    cost_ratio = trade.shares / (pos["shares"] + trade.shares)
                    pos["total_cost"] -= pos["total_cost"] * cost_ratio

            elif trade.trade_type == TradeType.SIP:
                # 定投：同买入
                if trade.amount is None:
                    continue
                shares = trade.amount / trade.nav_price
                pos["shares"] += shares
                pos["total_cost"] += trade.amount

        # 计算平均成本
        for fund_code, pos in positions.items():
            if pos["shares"] > 0:
                pos["avg_cost"] = pos["total_cost"] / pos["shares"]
            else:
                pos["avg_cost"] = 0.0

        return positions

    @staticmethod
    def calculate_unrealized_pnl(shares: float, avg_cost: float, current_nav: float) -> Optional[float]:
        """计算未实现盈亏"""
        if shares <= 0 or avg_cost <= 0 or current_nav <= 0:
            return None
        return (current_nav - avg_cost) * shares


class TradeService:
    """
    交易服务（领域逻辑）

    包含：创建交易、结算、查询持仓
    """

    def __init__(self, db_pool):  # type: ignore[no-untyped-def]
        self._db = db_pool

    async def create_trade(
        self,
        user_id: int,
        fund_code: str,
        trade_type: TradeType,
        amount: Optional[float],
        shares: Optional[float],
        nav_price: float,
        trade_date: date,
        client_msg_id: Optional[str] = None,
    ) -> Trade:
        """
        创建交易（带幂等检查）
        """
        # 生成幂等键
        idempotency_key = IdempotencyKey.generate(
            user_id=user_id,
            fund_code=fund_code,
            trade_type=trade_type,
            trade_date=trade_date,
            amount=amount,
            nav_price=nav_price,
            client_msg_id=client_msg_id,
        )

        # 检查是否已存在
        existing = await self._db.fetchrow(
            "SELECT * FROM simulation_trades WHERE idempotency_key = $1",
            idempotency_key,
        )

        if existing:
            return Trade(**dict(existing))

        # 创建新交易
        trade = Trade(
            trade_id=uuid4(),
            user_id=user_id,
            fund_code=fund_code,
            trade_type=trade_type,
            shares=shares,
            amount=amount,
            nav_price=nav_price,
            trade_date=trade_date,
            trade_status=TradeStatus.CREATED,
            idempotency_key=idempotency_key,
        )

        await self._db.execute(
            """
            INSERT INTO simulation_trades (
                trade_id, user_id, fund_code, trade_type, shares, amount,
                nav_price, trade_date, trade_status, idempotency_key
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """,
            trade.trade_id,
            trade.user_id,
            trade.fund_code,
            trade.trade_type.value,
            trade.shares,
            trade.amount,
            trade.nav_price,
            trade.trade_date,
            trade.trade_status.value,
            trade.idempotency_key,
        )

        return trade

    async def settle_trade(self, trade_id: UUID) -> Trade:
        """
        结算交易（T+1）
        """
        # 获取交易
        row = await self._db.fetchrow(
            "SELECT * FROM simulation_trades WHERE trade_id = $1",
            trade_id,
        )

        if not row:
            raise ValueError(f"交易 {trade_id} 不存在")

        trade = Trade(**dict(row))

        # 状态转换
        settled_trade = TradeStateMachine.transition(trade, TradeStatus.SETTLED)

        # 更新数据库
        await self._db.execute(
            """
            UPDATE simulation_trades
            SET trade_status = $1, settle_date = $2, updated_at = $3
            WHERE trade_id = $4
            """,
            settled_trade.trade_status.value,
            date.today(),
            settled_trade.updated_at,
            trade_id,
        )

        return settled_trade

    async def get_positions(self, user_id: int, as_of_date: Optional[date] = None) -> dict[str, dict]:
        """
        获取用户持仓（重建方式）
        """
        as_of_date = as_of_date or date.today()

        rows = await self._db.fetch(
            """
            SELECT * FROM simulation_trades
            WHERE user_id = $1
              AND trade_date <= $2
              AND trade_status IN ('confirmed', 'settled')
            ORDER BY trade_date ASC
            """,
            user_id,
            as_of_date,
        )

        trades = [Trade(**dict(row)) for row in rows]
        return PositionRebuilder.rebuild(trades, as_of_date)
