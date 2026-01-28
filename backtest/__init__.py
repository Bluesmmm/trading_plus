"""
回测与组合优化模块（简化版）

约束：
- 只消费事实数据层的指标
- 不得让模型编数字
- 仅用于模拟和历史分析，不提供买卖建议
"""

from backtest.engine import (
    BacktestEngine,
    BacktestResult,
    BacktestSignal,
    SignalType,
    Position,
    run_simple_backtest
)
from backtest.portfolio import (
    PortfolioOptimizer,
    PortfolioConfig,
    FundMetrics,
    OptimizationTarget,
    suggest_portfolio
)

__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "BacktestSignal",
    "SignalType",
    "Position",
    "run_simple_backtest",
    "PortfolioOptimizer",
    "PortfolioConfig",
    "FundMetrics",
    "OptimizationTarget",
    "suggest_portfolio",
]
