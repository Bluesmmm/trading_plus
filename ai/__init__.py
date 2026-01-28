"""
AI 分析模块

提供：
- 结构化输入/输出 Schema
- 单模型分析器
- 可追溯性持久化
"""

from ai.schema import (
    AIAnalysisOutput,
    FundFactsInput,
    AnalysisTraceability,
    ConfidenceLevel,
    RiskFlag,
    RecommendedCheck,
)
from ai.analyzer import FundAnalyzer, analyze_fund, get_analyzer
from ai.arbitrator import Arbitrator, ArbitrationStrategy, analyze_with_arbitration
from ai.persistence import AnalysisPersistence, save_analysis, get_persistence

__all__ = [
    "AIAnalysisOutput",
    "FundFactsInput", 
    "AnalysisTraceability",
    "ConfidenceLevel",
    "RiskFlag",
    "RecommendedCheck",
    "FundAnalyzer",
    "analyze_fund",
    "get_analyzer",
    "Arbitrator",
    "ArbitrationStrategy",
    "analyze_with_arbitration",
    "AnalysisPersistence",
    "save_analysis",
    "get_persistence",
]
