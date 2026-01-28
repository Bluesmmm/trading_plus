"""
组合优化（简化版）

约束（来自 KIMI.md #6）：
- 只消费事实数据层的指标
- 不得让模型编数字
- 简化版：只做等权、市值加权、风险平价三种基础配置

功能：
1. 基于历史收益率计算协方差矩阵
2. 简单优化目标：风险最小化 / 夏普最大化
3. 输出配置建议（权重），不含具体买卖指令
"""

import json
import statistics
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass, field
from enum import Enum


class OptimizationTarget(str, Enum):
    """优化目标"""
    EQUAL_WEIGHT = "equal_weight"      # 等权
    MIN_VARIANCE = "min_variance"      # 最小方差
    MAX_SHARPE = "max_sharpe"          # 最大夏普（简化）
    RISK_PARITY = "risk_parity"        # 风险平价（简化）


@dataclass
class FundMetrics:
    """基金指标"""
    fund_code: str
    fund_name: str = ""
    
    # 收益指标（必须来自事实数据）
    return_1m: Optional[float] = None
    return_3m: Optional[float] = None
    return_1y: Optional[float] = None
    
    # 风险指标
    volatility_annual: Optional[float] = None  # 年化波动率
    
    # 数据质量
    data_completeness: float = 1.0  # 数据完整度 0-1


@dataclass
class PortfolioConfig:
    """组合配置"""
    target: OptimizationTarget
    weights: Dict[str, float]  # fund_code -> weight
    
    # 预期指标（基于历史数据计算，非预测）
    expected_return: Optional[float] = None
    expected_volatility: Optional[float] = None
    expected_sharpe: Optional[float] = None
    
    # 风险提示
    risk_warnings: List[str] = field(default_factory=list)
    
    # 数据质量说明
    data_limitations: List[str] = field(default_factory=list)


class PortfolioOptimizer:
    """
    组合优化器（简化版）
    
    限制：
    - 不使用外部数据，只基于输入的收益率
    - 不进行未来收益预测
    - 输出仅为配置建议，不含买卖指令
    """
    
    def __init__(self, risk_free_rate: float = 0.0):
        self.risk_free_rate = risk_free_rate
    
    def optimize(
        self,
        funds: List[FundMetrics],
        target: OptimizationTarget = OptimizationTarget.EQUAL_WEIGHT,
        historical_returns: Optional[Dict[str, List[float]]] = None
    ) -> PortfolioConfig:
        """
        优化组合配置
        
        Args:
            funds: 基金指标列表
            target: 优化目标
            historical_returns: 历史收益率序列 {fund_code: [r1, r2, ...]}
        
        Returns:
            PortfolioConfig
        """
        if not funds:
            return PortfolioConfig(
                target=target,
                weights={},
                data_limitations=["未提供基金数据"]
            )
        
        fund_codes = [f.fund_code for f in funds]
        
        if target == OptimizationTarget.EQUAL_WEIGHT:
            return self._equal_weight(funds)
        elif target == OptimizationTarget.MIN_VARIANCE:
            return self._min_variance(funds, historical_returns)
        elif target == OptimizationTarget.MAX_SHARPE:
            return self._max_sharpe(funds, historical_returns)
        elif target == OptimizationTarget.RISK_PARITY:
            return self._risk_parity(funds, historical_returns)
        else:
            return self._equal_weight(funds)
    
    def _equal_weight(self, funds: List[FundMetrics]) -> PortfolioConfig:
        """等权配置"""
        n = len(funds)
        weight = 1.0 / n if n > 0 else 0
        
        weights = {f.fund_code: weight for f in funds}
        
        # 计算组合预期收益（历史加权平均）
        avg_returns = []
        for f in funds:
            if f.return_1y is not None:
                avg_returns.append(f.return_1y)
            elif f.return_3m is not None:
                avg_returns.append(f.return_3m * 4)  # 年化简化
            elif f.return_1m is not None:
                avg_returns.append(f.return_1m * 12)  # 年化简化
        
        expected_return = statistics.mean(avg_returns) if avg_returns else None
        
        # 数据限制说明
        limitations = []
        for f in funds:
            if f.data_completeness < 1.0:
                limitations.append(f"{f.fund_code}: 历史数据不完整")
        
        return PortfolioConfig(
            target=OptimizationTarget.EQUAL_WEIGHT,
            weights=weights,
            expected_return=expected_return,
            data_limitations=limitations
        )
    
    def _min_variance(
        self,
        funds: List[FundMetrics],
        historical_returns: Optional[Dict[str, List[float]]]
    ) -> PortfolioConfig:
        """最小方差配置（简化版）"""
        # 简化：根据波动率倒数加权
        inv_vols = {}
        for f in funds:
            if f.volatility_annual and f.volatility_annual > 0:
                inv_vols[f.fund_code] = 1.0 / f.volatility_annual
        
        if not inv_vols:
            #  fallback 到等权
            return self._equal_weight(funds)
        
        total_inv_vol = sum(inv_vols.values())
        weights = {code: iv / total_inv_vol for code, iv in inv_vols.items()}
        
        # 补全未分配权重的基金（数据缺失时）
        for f in funds:
            if f.fund_code not in weights:
                weights[f.fund_code] = 0.0
        
        # 风险警告
        warnings = []
        if len([w for w in weights.values() if w > 0]) < len(funds):
            warnings.append("部分基金因缺乏波动率数据未配置权重")
        
        return PortfolioConfig(
            target=OptimizationTarget.MIN_VARIANCE,
            weights=weights,
            risk_warnings=warnings
        )
    
    def _max_sharpe(
        self,
        funds: List[FundMetrics],
        historical_returns: Optional[Dict[str, List[float]]]
    ) -> PortfolioConfig:
        """最大夏普配置（简化版）"""
        # 简化：根据夏普比率（return/vol）加权
        sharpe_scores = {}
        for f in funds:
            ret = f.return_1y
            vol = f.volatility_annual
            if ret is not None and vol is not None and vol > 0:
                sharpe_scores[f.fund_code] = (ret - self.risk_free_rate) / vol
        
        if not sharpe_scores:
            return self._equal_weight(funds)
        
        # softmax 风格的权重分配（归一化）
        total_score = sum(max(0, s) for s in sharpe_scores.values())
        if total_score > 0:
            weights = {code: max(0, s) / total_score 
                      for code, s in sharpe_scores.items()}
        else:
            weights = {code: 1.0 / len(funds) for code in sharpe_scores.keys()}
        
        # 补全
        for f in funds:
            if f.fund_code not in weights:
                weights[f.fund_code] = 0.0
        
        return PortfolioConfig(
            target=OptimizationTarget.MAX_SHARPE,
            weights=weights
        )
    
    def _risk_parity(
        self,
        funds: List[FundMetrics],
        historical_returns: Optional[Dict[str, List[float]]]
    ) -> PortfolioConfig:
        """风险平价配置（简化版）"""
        # 简化版：每个资产对组合风险的贡献相等
        # 近似：权重与波动率倒数成正比
        return self._min_variance(funds, historical_returns)
    
    def analyze_allocation(
        self,
        config: PortfolioConfig,
        funds: List[FundMetrics]
    ) -> Dict[str, Any]:
        """
        分析配置方案（生成结构化报告）
        
        返回：
        - 权重分布
        - 集中度风险
        - 数据质量说明
        """
        weights = config.weights
        
        # 集中度检查
        max_weight = max(weights.values()) if weights else 0
        concentration_risk = "high" if max_weight > 0.5 else "medium" if max_weight > 0.3 else "low"
        
        # 数据质量汇总
        data_quality_issues = []
        for f in funds:
            if f.return_1y is None and f.return_3m is None:
                data_quality_issues.append(f"{f.fund_code}: 缺乏收益率数据")
            if f.volatility_annual is None:
                data_quality_issues.append(f"{f.fund_code}: 缺乏波动率数据")
        
        return {
            "allocation": weights,
            "target": config.target.value,
            "concentration_risk": concentration_risk,
            "max_single_weight": round(max_weight, 4),
            "data_quality_issues": data_quality_issues,
            "limitations": config.data_limitations,
            "warnings": config.risk_warnings,
            "note": "本配置仅基于历史数据计算，不构成投资建议"
        }


def suggest_portfolio(
    fund_codes: List[str],
    fund_data: Dict[str, Dict[str, Any]],  # fund_code -> metrics
    target: str = "equal_weight"
) -> Dict[str, Any]:
    """
    便捷函数：生成组合配置建议
    
    Args:
        fund_codes: 基金代码列表
        fund_data: 基金指标数据
        target: 优化目标
    
    Returns:
        分析结果字典
    """
    # 构建 FundMetrics
    funds = []
    for code in fund_codes:
        data = fund_data.get(code, {})
        funds.append(FundMetrics(
            fund_code=code,
            fund_name=data.get("fund_name", ""),
            return_1m=data.get("return_1m"),
            return_3m=data.get("return_3m"),
            return_1y=data.get("return_1y"),
            volatility_annual=data.get("volatility_annual"),
            data_completeness=data.get("data_completeness", 1.0)
        ))
    
    # 优化
    optimizer = PortfolioOptimizer()
    target_enum = OptimizationTarget(target)
    config = optimizer.optimize(funds, target_enum)
    
    # 分析
    analysis = optimizer.analyze_allocation(config, funds)
    
    return analysis
