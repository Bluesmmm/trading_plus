"""
单模型 AI 分析器

- 强制结构化 JSON 输出
- 输入哈希校验与缓存
- 不编造数据，只解释提供的事实
"""

import json
import hashlib
import time
from typing import Dict, Any, Optional, Tuple
from datetime import datetime

from ai.schema import (
    AIAnalysisOutput, 
    FundFactsInput, 
    AnalysisTraceability,
    ConfidenceLevel,
    RiskFlag,
    RecommendedCheck
)


class FundAnalyzer:
    """
    基金分析器（单模型版）
    
    职责：
    1. 接收结构化事实数据（FundFactsInput）
    2. 调用模型生成结构化分析
    3. 记录可追溯性信息
    """
    
    PROMPT_VERSION = "1.0.0"
    
    def __init__(self, model_name: str = "kimi-k2.5", model_version: str = "latest"):
        self.model_name = model_name
        self.model_version = model_version
        self._cache: Dict[str, Dict[str, Any]] = {}  # 简单内存缓存
    
    def _compute_input_hash(self, facts: Dict[str, Any]) -> str:
        """计算输入数据哈希（用于缓存和追溯）"""
        # 标准化：排序键，转字符串
        canonical = json.dumps(facts, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]
    
    def _build_prompt(self, facts: FundFactsInput) -> str:
        """
        构建分析提示词
        
        核心约束：
        - 只解释提供的数据
        - 不得编造数字或外部事实
        - 必须输出合法 JSON
        """
        facts_dict = facts.model_dump()
        
        # 移除 metadata 减少提示词长度
        facts_clean = {k: v for k, v in facts_dict.items() if k != "metadata" and v is not None}
        
        prompt = f"""你是一个基金分析助手。基于以下提供的事实数据进行分析。

【重要约束】
1. 只使用下面"事实数据"中提供的字段进行分析
2. 严禁编造任何数字、价格预测或外部未提供的信息
3. 如果数据缺失，在 unknowns 中明确说明
4. 不得给出"买入"/"卖出"建议，只做客观分析
5. 必须输出合法 JSON，不要包含 markdown 代码块标记

【事实数据】
```json
{json.dumps(facts_clean, indent=2, default=str)}
```

【输出格式】
必须严格符合以下 JSON Schema：
{{
  "summary": "分析摘要（客观描述，200字以内）",
  "risk_flags": [
    {{
      "severity": "low|medium|high|critical",
      "category": "liquidity|volatility|currency|concentration|credit|other",
      "description": "风险描述",
      "source_field": "来源字段名（如 fund_scale）"
    }}
  ],
  "assumptions": ["分析假设1", "分析假设2"],
  "unknowns": ["缺失信息1", "缺失信息2"],
  "recommended_checks": [
    {{
      "check_type": "建议核查的类型",
      "reason": "建议原因",
      "priority": 1
    }}
  ],
  "confidence": 0.75
}}

confidence 说明：
- 0.8-1.0: 数据完整，分析可靠
- 0.5-0.8: 部分数据缺失，分析有限
- 0.0-0.5: 数据严重不足，分析参考价值低

请直接输出 JSON，不要添加任何其他文字。"""
        return prompt
    
    def _parse_model_output(self, raw_output: str) -> AIAnalysisOutput:
        """解析模型输出为结构化对象"""
        # 清理可能的 markdown 代码块
        cleaned = raw_output.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
        
        try:
            data = json.loads(cleaned)
            return AIAnalysisOutput(**data)
        except json.JSONDecodeError as e:
            raise ValueError(f"模型输出不是合法 JSON: {e}\n输出: {raw_output[:200]}")
    
    def _call_model(self, prompt: str) -> str:
        """
        调用模型（占位实现）
        
        实际实现应接入 Kimi API 或其他模型
        """
        # TODO: 接入实际模型 API
        # 返回一个符合 schema 的示例响应用于测试
        return json.dumps({
            "summary": f"基于提供的数据，该基金净值日期为当日数据源，30日波动率为中等水平。",
            "risk_flags": [
                {
                    "severity": "medium",
                    "category": "liquidity",
                    "description": "数据未提供基金规模信息，无法评估流动性风险",
                    "source_field": "fund_scale"
                }
            ],
            "assumptions": [
                "假设提供的净值数据准确反映当前市场状况"
            ],
            "unknowns": [
                "缺乏基金规模数据",
                "缺乏最新持仓明细"
            ],
            "recommended_checks": [
                {
                    "check_type": "查看基金规模",
                    "reason": "评估流动性风险",
                    "priority": 2
                }
            ],
            "confidence": 0.65
        }, ensure_ascii=False)
    
    def _get_confidence_level(self, confidence: float) -> ConfidenceLevel:
        """将数值置信度转为等级"""
        if confidence >= 0.8:
            return ConfidenceLevel.HIGH
        elif confidence >= 0.5:
            return ConfidenceLevel.MEDIUM
        return ConfidenceLevel.LOW
    
    def analyze(
        self, 
        facts: FundFactsInput,
        use_cache: bool = True
    ) -> Tuple[AIAnalysisOutput, AnalysisTraceability]:
        """
        执行分析
        
        Args:
            facts: 事实数据输入
            use_cache: 是否使用缓存
            
        Returns:
            (分析输出, 可追溯性记录)
        """
        start_time = time.time()
        
        # 计算输入哈希
        facts_dict = facts.model_dump()
        input_hash = self._compute_input_hash(facts_dict)
        
        # 检查缓存
        cache_key = f"{facts.fund_code}:{input_hash}"
        if use_cache and cache_key in self._cache:
            cached = self._cache[cache_key]
            output = AIAnalysisOutput(**cached["output"])
            trace = AnalysisTraceability(
                analysis_id=cached["trace_id"],
                created_at=cached["created_at"],
                input_hash=input_hash,
                fund_code=facts.fund_code,
                facts_snapshot=facts_dict,
                model_name=self.model_name,
                model_version=self.model_version,
                prompt_version=self.PROMPT_VERSION,
                output_json=cached["output"],
                confidence_level=self._get_confidence_level(output.confidence),
                is_arbitrated=False,
                latency_ms=0,
                cache_hit=True
            )
            return output, trace
        
        # 构建提示词并调用模型
        prompt = self._build_prompt(facts)
        raw_output = self._call_model(prompt)
        
        # 解析输出
        output = self._parse_model_output(raw_output)
        
        # 计算耗时
        latency_ms = int((time.time() - start_time) * 1000)
        
        # 生成追溯记录
        analysis_id = f"ana_{input_hash}_{int(start_time)}"
        trace = AnalysisTraceability(
            analysis_id=analysis_id,
            created_at=datetime.now(),
            input_hash=input_hash,
            fund_code=facts.fund_code,
            facts_snapshot=facts_dict,
            model_name=self.model_name,
            model_version=self.model_version,
            prompt_version=self.PROMPT_VERSION,
            output_json=output.model_dump(),
            confidence_level=self._get_confidence_level(output.confidence),
            is_arbitrated=False,
            latency_ms=latency_ms,
            cache_hit=False
        )
        
        # 写入缓存
        if use_cache:
            self._cache[cache_key] = {
                "output": output.model_dump(),
                "trace_id": analysis_id,
                "created_at": datetime.now()
            }
        
        return output, trace


# 全局分析器实例
_analyzer: Optional[FundAnalyzer] = None


def get_analyzer() -> FundAnalyzer:
    """获取全局分析器实例"""
    global _analyzer
    if _analyzer is None:
        _analyzer = FundAnalyzer()
    return _analyzer


def analyze_fund(facts: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    便捷的基金分析接口
    
    Args:
        facts: 事实数据字典
        
    Returns:
        (分析结果字典, 追溯记录字典)
    """
    # 验证输入
    facts_input = FundFactsInput(**facts)
    
    # 执行分析
    analyzer = get_analyzer()
    output, trace = analyzer.analyze(facts_input)
    
    return output.model_dump(), trace.model_dump()
