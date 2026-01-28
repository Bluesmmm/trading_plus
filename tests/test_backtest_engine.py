"""
回测引擎单元测试
"""

import pytest
from backtest.engine import (
    BacktestEngine,
    BacktestSignal,
    SignalType,
    Position,
    run_simple_backtest
)


class TestPosition:
    """测试持仓"""
    
    def test_position_creation(self):
        """测试创建持仓"""
        pos = Position(fund_code="000001", shares=1000, cost_basis=1.2)
        
        assert pos.fund_code == "000001"
        assert pos.shares == 1000
        assert pos.cost_basis == 1.2
    
    def test_market_value(self):
        """测试市值计算"""
        pos = Position(fund_code="000001", shares=1000, cost_basis=1.2)
        
        assert pos.market_value(nav=1.5) == 1500.0
        assert pos.market_value(nav=1.2) == 1200.0
    
    def test_unrealized_pnl(self):
        """测试浮动盈亏"""
        pos = Position(fund_code="000001", shares=1000, cost_basis=1.2)
        
        # 盈利
        assert pos.unrealized_pnl(nav=1.5) == 300.0
        # 亏损
        assert pos.unrealized_pnl(nav=1.0) == -200.0
    
    def test_return_pct(self):
        """测试收益率"""
        pos = Position(fund_code="000001", shares=1000, cost_basis=1.2)
        
        assert pos.return_pct(nav=1.5) == 0.25  # 25%
        assert pos.return_pct(nav=1.2) == 0.0
        assert pos.return_pct(nav=0.96) == -0.2  # -20%


class TestBacktestEngine:
    """测试回测引擎"""
    
    def setup_method(self):
        """每个测试前创建引擎"""
        self.engine = BacktestEngine(initial_cash=100000.0, fee_rate=0.001)
    
    def test_initial_state(self):
        """测试初始状态"""
        assert self.engine.initial_cash == 100000.0
        assert self.engine.cash == 100000.0
        assert len(self.engine.positions) == 0
    
    def test_load_nav_data(self):
        """测试加载净值数据"""
        nav_series = [
            {"date": "2024-01-01", "nav": 1.0},
            {"date": "2024-01-02", "nav": 1.1},
            {"date": "2024-01-03", "nav": 1.05}
        ]
        
        result = self.engine.load_nav_data("000001", nav_series)
        
        assert result["2024-01-01"] == 1.0
        assert result["2024-01-02"] == 1.1
        assert result["2024-01-03"] == 1.05
    
    def test_buy_signal(self):
        """测试买入信号"""
        date_range = ["2024-01-01", "2024-01-02"]
        nav_data = {
            "000001": {"2024-01-01": 1.0, "2024-01-02": 1.1}
        }
        signals = [
            BacktestSignal(
                date="2024-01-01",
                fund_code="000001",
                signal=SignalType.BUY,
                amount=10000.0
            )
        ]
        
        result = self.engine.run(date_range, nav_data, signals)
        
        # 验证资金减少
        assert result.daily_snapshots[0].cash < 100000.0
        # 验证持仓增加
        assert "000001" in result.daily_snapshots[0].positions
        # 验证交易记录
        assert len(result.trades) == 1
        assert result.trades[0]["type"] == "buy"
    
    def test_sell_signal(self):
        """测试卖出信号"""
        date_range = ["2024-01-01", "2024-01-02"]
        nav_data = {
            "000001": {"2024-01-01": 1.0, "2024-01-02": 1.1}
        }
        signals = [
            BacktestSignal(
                date="2024-01-01",
                fund_code="000001",
                signal=SignalType.BUY,
                amount=10000.0
            ),
            BacktestSignal(
                date="2024-01-02",
                fund_code="000001",
                signal=SignalType.SELL,
                amount=None  # 卖出全部
            )
        ]
        
        result = self.engine.run(date_range, nav_data, signals)
        
        # 验证持仓清空
        assert "000001" not in result.daily_snapshots[-1].positions or \
               result.daily_snapshots[-1].positions["000001"].shares == 0
        # 验证交易记录
        assert len(result.trades) == 2
        assert result.trades[1]["type"] == "sell"
    
    def test_metrics_calculation(self):
        """测试指标计算"""
        # 创建一个简单的上涨趋势
        dates = [f"2024-01-{i:02d}" for i in range(1, 11)]
        navs = {d: 1.0 + i * 0.01 for i, d in enumerate(dates)}  # 从1.0涨到1.09
        
        date_range = dates
        nav_data = {"000001": navs}
        signals = [
            BacktestSignal(
                date=dates[0],
                fund_code="000001",
                signal=SignalType.BUY,
                amount=100000.0
            )
        ]
        
        result = self.engine.run(date_range, nav_data, signals)
        metrics = result.calculate_metrics()
        
        # 验证指标
        assert "total_return" in metrics
        assert "max_drawdown" in metrics
        assert "trade_count" in metrics
        assert metrics["total_return"] > 0  # 上涨趋势应该有正收益
        assert metrics["trade_count"] == 1


class TestRunSimpleBacktest:
    """测试便捷接口"""
    
    def test_buy_hold_strategy(self):
        """测试买入持有策略"""
        nav_data = [
            {"date": "2024-01-01", "nav": 1.0},
            {"date": "2024-01-02", "nav": 1.05},
            {"date": "2024-01-03", "nav": 1.03}
        ]
        
        result = run_simple_backtest("000001", nav_data, strategy="buy_hold")
        
        assert result.start_date == "2024-01-01"
        assert result.end_date == "2024-01-03"
        assert len(result.trades) == 1  # 只有一笔买入
        assert result.trades[0]["type"] == "buy"
    
    def test_empty_nav_data(self):
        """测试空数据"""
        result = run_simple_backtest("000001", [], strategy="buy_hold")
        
        assert result.start_date == ""
        assert result.end_date == ""
        assert len(result.trades) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
