"""
核心模块单元测试
"""

from datetime import date
from uuid import UUID

import pytest

from core.types import (
    AlertRule,
    AlertRuleParams,
    AlertRuleType,
    Fund,
    FundType,
    NAV,
    Position,
    QualityFlag,
    Trade,
    TradeStatus,
    TradeType,
)
from core.events import IdempotencyKey, PositionRebuilder, TradeStateMachine


class TestIdempotencyKey:
    """幂等键生成器测试"""

    def test_generate_same_params(self):
        """相同参数生成相同幂等键"""
        key1 = IdempotencyKey.generate(
            user_id=123,
            fund_code="000001",
            trade_type=TradeType.BUY,
            trade_date=date(2026, 1, 28),
            amount=1000.0,
            nav_price=1.5,
            client_msg_id="msg1",
        )

        key2 = IdempotencyKey.generate(
            user_id=123,
            fund_code="000001",
            trade_type=TradeType.BUY,
            trade_date=date(2026, 1, 28),
            amount=1000.0,
            nav_price=1.5,
            client_msg_id="msg1",
        )

        assert key1 == key2

    def test_generate_different_params(self):
        """不同参数生成不同幂等键"""
        key1 = IdempotencyKey.generate(
            user_id=123,
            fund_code="000001",
            trade_type=TradeType.BUY,
            trade_date=date(2026, 1, 28),
            amount=1000.0,
            nav_price=1.5,
        )

        key2 = IdempotencyKey.generate(
            user_id=123,
            fund_code="000001",
            trade_type=TradeType.BUY,
            trade_date=date(2026, 1, 28),
            amount=2000.0,  # 不同金额
            nav_price=1.5,
        )

        assert key1 != key2


class TestTradeStateMachine:
    """交易状态机测试"""

    @pytest.fixture
    def sample_trade(self):
        return Trade(
            trade_id=UUID("00000000-0000-0000-0000-000000000001"),
            user_id=123,
            fund_code="000001",
            trade_type=TradeType.BUY,
            amount=1000.0,
            nav_price=1.5,
            trade_date=date(2026, 1, 28),
            trade_status=TradeStatus.CREATED,
            idempotency_key="test-key",
        )

    def test_valid_transition_created_to_confirmed(self, sample_trade):
        """合法状态转换：created -> confirmed"""
        new_trade = TradeStateMachine.transition(sample_trade, TradeStatus.CONFIRMED)
        assert new_trade.trade_status == TradeStatus.CONFIRMED

    def test_invalid_transition_settled_to_created(self, sample_trade):
        """非法状态转换：settled -> created"""
        sample_trade.trade_status = TradeStatus.SETTLED
        with pytest.raises(ValueError):
            TradeStateMachine.transition(sample_trade, TradeStatus.CREATED)

    def test_immutability(self, sample_trade):
        """状态转换不修改原对象"""
        original_status = sample_trade.trade_status
        TradeStateMachine.transition(sample_trade, TradeStatus.CONFIRMED)
        assert sample_trade.trade_status == original_status


class TestPositionRebuilder:
    """持仓重建器测试"""

    @pytest.fixture
    def sample_trades(self):
        return [
            Trade(
                trade_id=UUID("00000000-0000-0000-0000-000000000001"),
                user_id=123,
                fund_code="000001",
                trade_type=TradeType.BUY,
                amount=1000.0,
                nav_price=1.0,
                trade_date=date(2026, 1, 25),
                trade_status=TradeStatus.SETTLED,
                idempotency_key="key1",
            ),
            Trade(
                trade_id=UUID("00000000-0000-0000-0000-000000000002"),
                user_id=123,
                fund_code="000001",
                trade_type=TradeType.BUY,
                amount=1000.0,
                nav_price=2.0,
                trade_date=date(2026, 1, 26),
                trade_status=TradeStatus.SETTLED,
                idempotency_key="key2",
            ),
        ]

    def test_rebuild_buy_trades(self, sample_trades):
        """重建买入交易"""
        positions = PositionRebuilder.rebuild(sample_trades, date(2026, 1, 27))

        assert "000001" in positions
        assert positions["000001"]["shares"] == 1500.0  # 1000/1 + 1000/2
        assert positions["000001"]["total_cost"] == 2000.0
        assert positions["000001"]["avg_cost"] == 2000.0 / 1500.0

    def test_ignore unsettled_trades(self, sample_trades):
        """忽略未结算交易"""
        sample_trades[0].trade_status = TradeStatus.CREATED
        positions = PositionRebuilder.rebuild(sample_trades, date(2026, 1, 27))

        # 只计算第二笔已结算交易
        assert positions["000001"]["shares"] == 500.0


class TestTypes:
    """类型验证测试"""

    def test_fund_creation(self):
        """基金类型创建"""
        fund = Fund(
            fund_code="000001",
            name="测试基金",
            fund_type=FundType.MUTUAL,
        )
        assert fund.fund_code == "000001"
        assert fund.currency == "CNY"

    def test_nav_quality_flags(self):
        """净值质量标记"""
        nav = NAV(
            fund_code="000001",
            nav_date=date(2026, 1, 28),
            nav=1.5,
            data_source="eastmoney",
            last_updated_at=date(2026, 1, 28),
            quality_flags=[QualityFlag.OK],
        )
        assert QualityFlag.OK in nav.quality_flags

    def test_alert_rule_params(self):
        """预警规则参数"""
        params = AlertRuleParams(threshold_pct=10.0)
        assert params.threshold_pct == 10.0
        assert params.window_days == 1  # 默认值
