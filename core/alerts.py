"""
告警引擎

功能：规则解析、触发检测、去重、冷却窗口
"""

from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID, uuid4

from core.types import (
    AlertEvent,
    AlertRule,
    AlertRuleParams,
    AlertRuleType,
    AlertStatus,
    QualityFlag,
)


class DedupKey:
    """
    去重键生成器

    格式：user_id:fund_code:rule_type:window_bucket
    window_bucket 按冷却窗口分桶，防止短时间重复触发
    """

    @staticmethod
    def generate(
        user_id: int,
        fund_code: str,
        rule_type: AlertRuleType,
        cooldown_seconds: int,
        triggered_at: datetime,
    ) -> str:
        """生成去重键"""
        # 计算时间桶（按冷却窗口向下取整）
        window_bucket = int(triggered_at.timestamp() // cooldown_seconds)

        parts = [
            str(user_id),
            fund_code,
            rule_type.value,
            str(window_bucket),
        ]
        return ":".join(parts)


class RuleEvaluator:
    """
    规则评估器

    根据规则参数和当前数据，判断是否触发预警
    """

    @staticmethod
    def evaluate_threshold(
        current_nav: float,
        params: AlertRuleParams,
    ) -> bool:
        """阈值规则：净值超过阈值"""
        if params.threshold_value is None:
            return False
        return current_nav >= params.threshold_value

    @staticmethod
    def evaluate_drawdown(
        nav_series: list[float],
        params: AlertRuleParams,
    ) -> tuple[bool, float]:
        """
        回撤规则：从最高点回落超过阈值

        返回：(是否触发, 当前回撤)
        """
        if not nav_series:
            return False, 0.0

        peak = max(nav_series)
        current = nav_series[-1]

        if peak == 0:
            return False, 0.0

        drawdown_pct = (peak - current) / peak * 100

        if params.threshold_pct is not None:
            return drawdown_pct >= params.threshold_pct, drawdown_pct

        return False, drawdown_pct

    @staticmethod
    def evaluate_volatility(
        nav_series: list[float],
        params: AlertRuleParams,
    ) -> tuple[bool, float]:
        """
        波动率规则：年化波动率超过阈值

        返回：(是否触发, 当前波动率)
        """
        if len(nav_series) < 2:
            return False, 0.0

        # 计算日收益率
        returns = []
        for i in range(1, len(nav_series)):
            if nav_series[i - 1] > 0:
                ret = (nav_series[i] - nav_series[i - 1]) / nav_series[i - 1]
                returns.append(ret)

        if not returns:
            return False, 0.0

        # 计算标准差（年化）
        import statistics

        std_dev = statistics.stdev(returns) if len(returns) > 1 else 0.0
        annualized_vol = std_dev * (252 ** 0.5) * 100  # 年化百分比

        if params.threshold_pct is not None:
            return annualized_vol >= params.threshold_pct, annualized_vol

        return False, annualized_vol

    @staticmethod
    def evaluate_new_high(
        nav_series: list[float],
    ) -> bool:
        """
        创新高规则：当前净值是窗口期最高
        """
        if not nav_series:
            return False
        return nav_series[-1] == max(nav_series)

    @staticmethod
    def evaluate_new_low(
        nav_series: list[float],
    ) -> bool:
        """
        创新低规则：当前净值是窗口期最低
        """
        if not nav_series:
            return False
        return nav_series[-1] == min(nav_series)


class AlertEngine:
    """
    预警引擎主类

    协调规则评估、去重、冷却窗口
    """

    def __init__(self, db_pool):  # type: ignore[no-untyped-def]
        self._db = db_pool

    async def check_rule(
        self,
        rule: AlertRule,
        current_nav: float,
        nav_series: list[float],
        triggered_at: datetime,
    ) -> Optional[AlertEvent]:
        """
        检查规则是否触发（带去重和冷却）
        """
        # 评估规则
        triggered = False
        payload = {}

        if rule.rule_type == AlertRuleType.THRESHOLD:
            triggered = RuleEvaluator.evaluate_threshold(current_nav, rule.params)
            payload = {"current_nav": current_nav, "threshold": rule.params.threshold_value}

        elif rule.rule_type == AlertRuleType.DRAWDOWN:
            triggered, drawdown = RuleEvaluator.evaluate_drawdown(nav_series, rule.params)
            payload = {"drawdown_pct": drawdown, "threshold_pct": rule.params.threshold_pct}

        elif rule.rule_type == AlertRuleType.VOLATILITY:
            triggered, volatility = RuleEvaluator.evaluate_volatility(nav_series, rule.params)
            payload = {"volatility_pct": volatility, "threshold_pct": rule.params.threshold_pct}

        elif rule.rule_type == AlertRuleType.NEW_HIGH:
            triggered = RuleEvaluator.evaluate_new_high(nav_series)
            payload = {"current_nav": current_nav, "is_new_high": triggered}

        elif rule.rule_type == AlertRuleType.NEW_LOW:
            triggered = RuleEvaluator.evaluate_new_low(nav_series)
            payload = {"current_nav": current_nav, "is_new_low": triggered}

        if not triggered:
            return None

        # 生成去重键
        fund_code = rule.fund_code or "ALL"
        dedup_key = DedupKey.generate(
            user_id=rule.user_id,
            fund_code=fund_code,
            rule_type=rule.rule_type,
            cooldown_seconds=rule.cooldown_seconds,
            triggered_at=triggered_at,
        )

        # 检查去重
        existing = await self._db.fetchrow(
            """
            SELECT event_id, status, sent_at
            FROM alert_events
            WHERE dedup_key = $1
            ORDER BY created_at DESC
            LIMIT 1
            """,
            dedup_key,
        )

        # 如果存在且在冷却期内，抑制
        if existing:
            event = dict(existing)
            if event["status"] == "sent":
                sent_at = event["sent_at"]
                if sent_at and (triggered_at - sent_at).total_seconds() < rule.cooldown_seconds:
                    # 在冷却期内，抑制
                    return AlertEvent(
                        event_id=uuid4(),
                        rule_id=rule.rule_id,
                        user_id=rule.user_id,
                        fund_code=fund_code,
                        rule_type=rule.rule_type,
                        triggered_at=triggered_at,
                        payload=payload,
                        dedup_key=dedup_key,
                        status=AlertStatus.SUPPRESSED,
                    )

        # 创建新预警事件
        event = AlertEvent(
            event_id=uuid4(),
            rule_id=rule.rule_id,
            user_id=rule.user_id,
            fund_code=fund_code,
            rule_type=rule.rule_type,
            triggered_at=triggered_at,
            payload=payload,
            dedup_key=dedup_key,
            status=AlertStatus.PENDING,
        )

        await self._db.execute(
            """
            INSERT INTO alert_events (
                event_id, rule_id, user_id, fund_code, rule_type,
                triggered_at, payload, dedup_key, status
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            event.event_id,
            event.rule_id,
            event.user_id,
            event.fund_code,
            event.rule_type.value,
            event.triggered_at,
            event.payload,
            event.dedup_key,
            event.status.value,
        )

        return event

    async def create_rule(
        self,
        user_id: int,
        fund_code: Optional[str],
        rule_type: AlertRuleType,
        params: AlertRuleParams,
        cooldown_seconds: int = 3600,
    ) -> AlertRule:
        """创建预警规则"""
        rule = AlertRule(
            rule_id=uuid4(),
            user_id=user_id,
            fund_code=fund_code,
            rule_type=rule_type,
            params=params,
            cooldown_seconds=cooldown_seconds,
        )

        await self._db.execute(
            """
            INSERT INTO alert_rules (
                rule_id, user_id, fund_code, rule_type, params, cooldown_seconds
            ) VALUES ($1, $2, $3, $4, $5, $6)
            """,
            rule.rule_id,
            rule.user_id,
            rule.fund_code,
            rule.rule_type.value,
            rule.params.model_dump(),
            rule.cooldown_seconds,
        )

        return rule

    async def list_rules(self, user_id: int) -> list[AlertRule]:
        """列出用户所有规则"""
        rows = await self._db.fetch(
            "SELECT * FROM alert_rules WHERE user_id = $1 ORDER BY created_at DESC",
            user_id,
        )

        return [AlertRule(**dict(row)) for row in rows]

    async def get_pending_alerts(self, limit: int = 100) -> list[AlertEvent]:
        """获取待发送的预警"""
        rows = await self._db.fetch(
            """
            SELECT * FROM alert_events
            WHERE status = 'pending'
            ORDER BY triggered_at ASC
            LIMIT $1
            """,
            limit,
        )

        return [AlertEvent(**dict(row)) for row in rows]

    async def mark_sent(self, event_id: UUID) -> None:
        """标记预警已发送"""
        await self._db.execute(
            """
            UPDATE alert_events
            SET status = 'sent', sent_at = NOW()
            WHERE event_id = $1
            """,
            event_id,
        )

    async def mark_failed(self, event_id: UUID, error: str) -> None:
        """标记预警发送失败"""
        await self._db.execute(
            """
            UPDATE alert_events
            SET status = 'failed', error = $1
            WHERE event_id = $2
            """,
            error,
            event_id,
        )
