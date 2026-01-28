"""
回测引擎（简化版）

约束（来自 KIMI.md #6）：
- 只消费事实数据层的指标（净值、收益率等）
- 不得让模型编数字
- 模拟交易逻辑与核心系统保持一致

本回测仅用于：
1. 基于历史净值的简单收益计算
2. 模拟调仓的效果对比
3. 风险指标（波动率、最大回撤）计算
"""

import json
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum


class SignalType(str, Enum):
    """信号类型"""
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class BacktestSignal:
    """回测信号"""
    date: str
    fund_code: str
    signal: SignalType
    amount: Optional[float] = None  # 金额，None表示全部
    reason: str = ""  # 信号原因（客观描述）


@dataclass
class Position:
    """持仓"""
    fund_code: str
    shares: float = 0.0  # 份额
    cost_basis: float = 0.0  # 成本单价
    
    @property
    def market_value(self, nav: float = 0.0) -> float:
        """市值"""
        return self.shares * nav
    
    @property
    def unrealized_pnl(self, nav: float = 0.0) -> float:
        """浮动盈亏"""
        if self.shares == 0:
            return 0.0
        return self.shares * (nav - self.cost_basis)
    
    @property
    def return_pct(self, nav: float = 0.0) -> float:
        """收益率"""
        if self.cost_basis == 0:
            return 0.0
        return (nav - self.cost_basis) / self.cost_basis


@dataclass
class DailySnapshot:
    """每日账户快照"""
    date: str
    cash: float
    positions: Dict[str, Position]  # fund_code -> Position
    nav_data: Dict[str, float]  # fund_code -> NAV
    
    @property
    def total_value(self) -> float:
        """总资产"""
        total = self.cash
        for fund_code, pos in self.positions.items():
            nav = self.nav_data.get(fund_code, 0.0)
            total += pos.market_value(nav)
        return total
    
    @property
    def position_values(self) -> Dict[str, float]:
        """各持仓市值"""
        result = {}
        for fund_code, pos in self.positions.items():
            nav = self.nav_data.get(fund_code, 0.0)
            result[fund_code] = pos.market_value(nav)
        return result


@dataclass
class BacktestResult:
    """回测结果"""
    # 基础信息
    start_date: str
    end_date: str
    initial_cash: float
    
    # 每日快照序列
    daily_snapshots: List[DailySnapshot] = field(default_factory=list)
    
    # 交易记录
    trades: List[Dict[str, Any]] = field(default_factory=list)
    
    # 计算指标（回填）
    metrics: Dict[str, float] = field(default_factory=dict)
    
    def calculate_metrics(self) -> Dict[str, float]:
        """计算回测指标"""
        if len(self.daily_snapshots) < 2:
            return {}
        
        values = [s.total_value for s in self.daily_snapshots]
        dates = [s.date for s in self.daily_snapshots]
        
        # 总收益率
        total_return = (values[-1] - values[0]) / values[0] if values[0] > 0 else 0
        
        # 日收益率序列
        daily_returns = []
        for i in range(1, len(values)):
            if values[i-1] > 0:
                daily_returns.append((values[i] - values[i-1]) / values[i-1])
        
        # 年化收益率（简化按252交易日）
        n_days = len(daily_returns)
        annual_return = (1 + total_return) ** (252 / n_days) - 1 if n_days > 0 and total_return > -1 else 0
        
        # 波动率（年化）
        import statistics
        if len(daily_returns) > 1:
            daily_vol = statistics.stdev(daily_returns)
            annual_vol = daily_vol * (252 ** 0.5)
        else:
            annual_vol = 0
        
        # 最大回撤
        max_drawdown = 0
        peak = values[0]
        for v in values:
            if v > peak:
                peak = v
            dd = (peak - v) / peak if peak > 0 else 0
            if dd > max_drawdown:
                max_drawdown = dd
        
        # Sharpe 简化版（假设无风险利率0）
        sharpe = annual_return / annual_vol if annual_vol > 0 else 0
        
        self.metrics = {
            "total_return": round(total_return, 4),
            "annual_return": round(annual_return, 4),
            "annual_volatility": round(annual_vol, 4),
            "max_drawdown": round(max_drawdown, 4),
            "sharpe_ratio": round(sharpe, 4),
            "final_value": round(values[-1], 2),
            "trade_count": len(self.trades)
        }
        
        return self.metrics


class BacktestEngine:
    """
    回测引擎（简化版）
    
    功能：
    1. 基于历史净值数据模拟交易
    2. 支持买入/卖出信号回测
    3. 计算基础风险指标
    
    限制：
    - 只使用提供的净值数据，不获取外部数据
    - 不考虑交易费用（或固定费率）
    - T+1 确认简化处理（当日买入次日确认）
    """
    
    def __init__(
        self,
        initial_cash: float = 100000.0,
        fee_rate: float = 0.001  # 千分之一手续费
    ):
        self.initial_cash = initial_cash
        self.fee_rate = fee_rate
        self.cash = initial_cash
        self.positions: Dict[str, Position] = {}
        self.trades: List[Dict[str, Any]] = []
        self.snapshots: List[DailySnapshot] = []
    
    def load_nav_data(
        self,
        fund_code: str,
        nav_series: List[Dict[str, Any]]  # [{date: "2024-01-01", nav: 1.2345}, ...]
    ) -> Dict[str, float]:
        """
        加载基金净值数据
        
        Args:
            fund_code: 基金代码
            nav_series: 净值序列
            
        Returns:
            date -> nav 映射
        """
        return {item["date"]: item["nav"] for item in nav_series}
    
    def run(
        self,
        date_range: List[str],  # 回测日期列表（升序）
        nav_data: Dict[str, Dict[str, float]],  # fund_code -> {date -> nav}
        signals: List[BacktestSignal]  # 交易信号
    ) -> BacktestResult:
        """
        执行回测
        
        Args:
            date_range: 回测日期范围
            nav_data: 各基金净值数据
            signals: 交易信号列表
            
        Returns:
            BacktestResult
        """
        # 按日期索引信号
        signal_by_date: Dict[str, List[BacktestSignal]] = {}
        for sig in signals:
            if sig.date not in signal_by_date:
                signal_by_date[sig.date] = []
            signal_by_date[sig.date].append(sig)
        
        for date in date_range:
            # 获取当日净值
            today_nav = {
                fund_code: navs.get(date, 0.0)
                for fund_code, navs in nav_data.items()
            }
            
            # 处理当日信号（简化：当日信号当日成交，实际应为T+1）
            if date in signal_by_date:
                for signal in signal_by_date[date]:
                    self._execute_signal(signal, today_nav.get(signal.fund_code, 0.0), date)
            
            # 记录快照
            snapshot = DailySnapshot(
                date=date,
                cash=self.cash,
                positions={k: Position(k, v.shares, v.cost_basis) 
                          for k, v in self.positions.items()},
                nav_data=today_nav
            )
            self.snapshots.append(snapshot)
        
        # 构建结果
        result = BacktestResult(
            start_date=date_range[0] if date_range else "",
            end_date=date_range[-1] if date_range else "",
            initial_cash=self.initial_cash,
            daily_snapshots=self.snapshots,
            trades=self.trades
        )
        result.calculate_metrics()
        
        return result
    
    def _execute_signal(
        self,
        signal: BacktestSignal,
        nav: float,
        date: str
    ):
        """执行交易信号"""
        if nav <= 0:
            return
        
        fund_code = signal.fund_code
        
        if signal.signal == SignalType.BUY and signal.amount:
            # 买入
            amount = min(signal.amount, self.cash)
            fee = amount * self.fee_rate
            amount_after_fee = amount - fee
            shares = amount_after_fee / nav
            
            # 更新持仓（简化平均成本）
            if fund_code not in self.positions:
                self.positions[fund_code] = Position(fund_code)
            
            pos = self.positions[fund_code]
            total_cost = pos.shares * pos.cost_basis + amount
            pos.shares += shares
            pos.cost_basis = total_cost / pos.shares if pos.shares > 0 else 0
            
            self.cash -= amount
            
            self.trades.append({
                "date": date,
                "fund_code": fund_code,
                "type": "buy",
                "amount": amount,
                "shares": shares,
                "nav": nav,
                "fee": fee
            })
        
        elif signal.signal == SignalType.SELL:
            # 卖出
            if fund_code not in self.positions or self.positions[fund_code].shares <= 0:
                return
            
            pos = self.positions[fund_code]
            shares_to_sell = pos.shares if signal.amount is None else signal.amount / nav
            shares_to_sell = min(shares_to_sell, pos.shares)
            
            amount = shares_to_sell * nav
            fee = amount * self.fee_rate
            amount_after_fee = amount - fee
            
            pos.shares -= shares_to_sell
            if pos.shares <= 0:
                del self.positions[fund_code]
            
            self.cash += amount_after_fee
            
            self.trades.append({
                "date": date,
                "fund_code": fund_code,
                "type": "sell",
                "amount": amount,
                "shares": shares_to_sell,
                "nav": nav,
                "fee": fee
            })


def run_simple_backtest(
    fund_code: str,
    nav_data: List[Dict[str, Any]],
    strategy: str = "buy_hold"
) -> BacktestResult:
    """
    便捷函数：运行简单回测
    
    Args:
        fund_code: 基金代码
        nav_data: 净值数据 [{date, nav}, ...]
        strategy: 策略类型 (buy_hold)
    
    Returns:
        BacktestResult
    """
    # 提取日期列表
    date_range = [d["date"] for d in nav_data]
    nav_map = {fund_code: {d["date"]: d["nav"] for d in nav_data}}
    
    engine = BacktestEngine(initial_cash=100000.0)
    
    signals = []
    if strategy == "buy_hold" and nav_data:
        # 第一天买入
        signals.append(BacktestSignal(
            date=nav_data[0]["date"],
            fund_code=fund_code,
            signal=SignalType.BUY,
            amount=100000.0,
            reason="买入持有策略"
        ))
    
    return engine.run(date_range, nav_map, signals)
