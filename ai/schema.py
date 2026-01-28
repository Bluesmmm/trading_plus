"""
AI 结构化输出 Schema 定义

约束（来自 KIMI.md #6）：
- 输入：只允许来自服务端生成的 facts JSON（含 data_source/last_updated_at）
- 输出：强制 JSON schema（字段：summary、risk_flags、assumptions、unknowns、recommended_checks、confidence）
- 禁止输出：必须买/必须卖、精确价格预测、编造持仓/公告等外部事实
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum


class ConfidenceLevel(str, Enum):
    """置信度等级"""
    HIGH = "high"      # > 0.8
    MEDIUM = "medium"  # 0.5 - 0.8
    LOW = "low"        # < 0.5


class RiskFlag(BaseModel):
    """风险标记项"""
    severity: str = Field(..., description="风险等级: low/medium/high/critical")
    category: str = Field(..., description="风险类别: liquidity/volatility/currency/concentration/etc")
    description: str = Field(..., description="风险描述")
    source_field: Optional[str] = Field(None, description="来源字段（追溯用）")


class RecommendedCheck(BaseModel):
    """建议核查项"""
    check_type: str = Field(..., description="核查类型")
    reason: str = Field(..., description="建议原因")
    priority: int = Field(..., ge=1, le=5, description="优先级 1-5")


class AIAnalysisOutput(BaseModel):
    """
    AI 分析结构化输出 Schema
    
    禁止包含：
    - 具体买卖建议（如"应该买入"）
    - 精确价格预测
    - 编造的事实数据
    """
    summary: str = Field(
        ..., 
        description="分析摘要（客观描述，不含买卖建议）",
        max_length=500
    )
    risk_flags: List[RiskFlag] = Field(
        default_factory=list,
        description="识别的风险标记"
    )
    assumptions: List[str] = Field(
        default_factory=list,
        description="分析假设（明确声明）"
    )
    unknowns: List[str] = Field(
        default_factory=list,
        description="未知/缺失信息（诚实披露）"
    )
    recommended_checks: List[RecommendedCheck] = Field(
        default_factory=list,
        description="建议用户核查的事项"
    )
    confidence: float = Field(
        ..., 
        ge=0.0, 
        le=1.0,
        description="整体置信度 0-1"
    )
    
    class Config:
        json_schema_extra = {
            "examples": [{
                "summary": "基于提供的净值数据，该基金近30日波动率在同类中处于中等水平。",
                "risk_flags": [
                    {
                        "severity": "medium",
                        "category": "liquidity",
                        "description": "基金规模较小，大额赎回可能存在流动性压力",
                        "source_field": "fund_scale"
                    }
                ],
                "assumptions": [
                    "假设提供的历史净值数据完整准确"
                ],
                "unknowns": [
                    "缺乏最新季报持仓明细",
                    "未获取基金经理近期访谈信息"
                ],
                "recommended_checks": [
                    {
                        "check_type": "查看最新季报",
                        "reason": "确认前十大持仓是否有重大变化",
                        "priority": 2
                    }
                ],
                "confidence": 0.72
            }]
        }


class FundFactsInput(BaseModel):
    """
    基金事实数据输入 Schema
    
    来源：服务端生成，必须包含 data_source 和 last_updated_at
    """
    fund_code: str = Field(..., description="基金代码")
    fund_name: str = Field(..., description="基金名称")
    nav: Optional[float] = Field(None, description="单位净值")
    nav_date: Optional[str] = Field(None, description="净值日期")
    
    # 数据源追溯字段（强制）
    data_source: str = Field(..., description="数据来源标识")
    last_updated_at: datetime = Field(..., description="数据最后更新时间")
    
    # 可选扩展字段
    fund_type: Optional[str] = Field(None, description="基金类型")
    fund_scale: Optional[float] = Field(None, description="基金规模（亿元）")
    manager: Optional[str] = Field(None, description="基金经理")
    volatility_30d: Optional[float] = Field(None, description="30日波动率")
    return_1m: Optional[float] = Field(None, description="近1月收益率")
    return_3m: Optional[float] = Field(None, description="近3月收益率")
    return_1y: Optional[float] = Field(None, description="近1年收益率")
    
    # 额外元数据
    metadata: Dict[str, Any] = Field(default_factory=dict, description="附加元数据")


class AnalysisTraceability(BaseModel):
    """
    分析可追溯性记录（落库用）
    
    记录每次 AI 分析的完整上下文，用于审计和回溯
    """
    # 唯一标识
    analysis_id: str = Field(..., description="分析ID（UUID）")
    created_at: datetime = Field(..., description="分析时间")
    
    # 输入信息
    input_hash: str = Field(..., description="输入数据哈希（SHA-256）")
    fund_code: str = Field(..., description="分析的基金代码")
    facts_snapshot: Dict[str, Any] = Field(..., description="输入事实数据快照")
    
    # 模型信息
    model_name: str = Field(..., description="使用的模型名称")
    model_version: str = Field(..., description="模型版本")
    prompt_version: str = Field(..., description="提示词模板版本")
    
    # 输出结果
    output_json: Dict[str, Any] = Field(..., description="结构化输出（JSON）")
    confidence_level: ConfidenceLevel = Field(..., description="置信度等级")
    
    # 裁决信息（多模型时用）
    is_arbitrated: bool = Field(default=False, description="是否经过裁决")
    arbitration_method: Optional[str] = Field(None, description="裁决方法")
    model_outputs: Optional[List[Dict[str, Any]]] = Field(None, description="各模型原始输出")
    
    # 元数据
    latency_ms: int = Field(..., description="分析耗时（毫秒）")
    cache_hit: bool = Field(default=False, description="是否命中缓存")


def get_output_schema() -> Dict[str, Any]:
    """获取输出 JSON Schema（用于模型强制输出）"""
    return AIAnalysisOutput.model_json_schema()


def validate_facts_input(data: Dict[str, Any]) -> FundFactsInput:
    """验证输入事实数据"""
    return FundFactsInput(**data)


def validate_analysis_output(data: Dict[str, Any]) -> AIAnalysisOutput:
    """验证分析输出"""
    return AIAnalysisOutput(**data)
