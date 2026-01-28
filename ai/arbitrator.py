"""
三模型裁决器

功能：
1. 调用多个模型并行分析
2. 对比输出差异
3. 裁决最终结论
4. 记录各模型输出与裁决理由

裁决策略（可配置）：
- consensus: 多数投票（默认）
- confidence_weighted: 置信度加权
- strict: 必须一致，否则降低置信度
"""

import json
import statistics
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, as_completed

from ai.schema import AIAnalysisOutput, FundFactsInput, AnalysisTraceability, ConfidenceLevel
from ai.analyzer import FundAnalyzer


class ArbitrationStrategy(str, Enum):
    """裁决策略"""
    CONSENSUS = "consensus"                    # 多数投票
    CONFIDENCE_WEIGHTED = "confidence_weighted"  # 置信度加权
    STRICT = "strict"                          # 严格一致


@dataclass
class ModelOutput:
    """单个模型输出"""
    model_name: str
    output: AIAnalysisOutput
    latency_ms: int
    error: Optional[str] = None


@dataclass
class ArbitrationResult:
    """裁决结果"""
    final_output: AIAnalysisOutput
    arbitration_method: str
    model_outputs: List[Dict[str, Any]]
    consensus_level: float  # 一致程度 0-1
    divergence_flags: List[str]  # 分歧标记


class Arbitrator:
    """
    多模型裁决器
    
    当前支持模型：
    - kimi-k2.5
    - glm-4.7
    - （预留第三个模型位）
    """
    
    def __init__(
        self,
        models: List[str] = None,
        strategy: ArbitrationStrategy = ArbitrationStrategy.CONSENSUS
    ):
        self.models = models or ["kimi-k2.5", "glm-4.7"]
        self.strategy = strategy
        self.analyzers = {
            model: FundAnalyzer(model_name=model)
            for model in self.models
        }
    
    def arbitrate(
        self,
        facts: FundFactsInput,
        timeout_ms: int = 30000
    ) -> Tuple[AIAnalysisOutput, AnalysisTraceability]:
        """
        执行多模型分析并裁决
        
        Args:
            facts: 事实数据
            timeout_ms: 超时时间
            
        Returns:
            (裁决后的输出, 可追溯性记录)
        """
        import time
        start_time = time.time()
        
        # 并行调用各模型
        model_outputs = self._call_models_parallel(facts, timeout_ms)
        
        # 执行裁决
        result = self._arbitrate_outputs(model_outputs)
        
        # 构建最终输出
        final_output = result.final_output
        
        # 计算总耗时
        latency_ms = int((time.time() - start_time) * 1000)
        
        # 计算输入哈希（使用主分析器的逻辑）
        facts_dict = facts.model_dump()
        analyzer = list(self.analyzers.values())[0]
        input_hash = analyzer._compute_input_hash(facts_dict)
        
        # 构建可追溯性记录
        analysis_id = f"arb_{input_hash}_{int(start_time)}"
        trace = AnalysisTraceability(
            analysis_id=analysis_id,
            created_at=__import__('datetime').datetime.now(),
            input_hash=input_hash,
            fund_code=facts.fund_code,
            facts_snapshot=facts_dict,
            model_name="multi-model-arbitrated",
            model_version="1.0",
            prompt_version="multi-v1",
            output_json=final_output.model_dump(),
            confidence_level=self._get_confidence_level(final_output.confidence),
            is_arbitrated=True,
            arbitration_method=result.arbitration_method,
            model_outputs=[mo.output.model_dump() for mo in model_outputs if mo.error is None],
            latency_ms=latency_ms,
            cache_hit=False
        )
        
        return final_output, trace
    
    def _call_models_parallel(
        self,
        facts: FundFactsInput,
        timeout_ms: int
    ) -> List[ModelOutput]:
        """并行调用多个模型"""
        results = []
        
        # TODO: 实际实现应使用线程池并行调用
        # 简化版：串行调用
        for model_name, analyzer in self.analyzers.items():
            try:
                output, trace = analyzer.analyze(facts, use_cache=False)
                results.append(ModelOutput(
                    model_name=model_name,
                    output=output,
                    latency_ms=trace.latency_ms
                ))
            except Exception as e:
                results.append(ModelOutput(
                    model_name=model_name,
                    output=AIAnalysisOutput(
                        summary="",
                        confidence=0.0,
                        risk_flags=[],
                        assumptions=[],
                        unknowns=[f"模型调用失败: {str(e)}"],
                        recommended_checks=[]
                    ),
                    latency_ms=0,
                    error=str(e)
                ))
        
        return results
    
    def _arbitrate_outputs(
        self,
        model_outputs: List[ModelOutput]
    ) -> ArbitrationResult:
        """执行裁决逻辑"""
        valid_outputs = [mo for mo in model_outputs if mo.error is None]
        
        if not valid_outputs:
            # 全部失败
            return ArbitrationResult(
                final_output=AIAnalysisOutput(
                    summary="所有模型调用失败",
                    confidence=0.0,
                    risk_flags=[],
                    assumptions=[],
                    unknowns=["无法获取任何模型输出"],
                    recommended_checks=[{"check_type": "检查模型服务", "reason": "所有模型调用失败", "priority": 1}]
                ),
                arbitration_method="fallback",
                model_outputs=[],
                consensus_level=0.0,
                divergence_flags=["all_models_failed"]
            )
        
        if len(valid_outputs) == 1:
            # 只有一个模型成功
            return ArbitrationResult(
                final_output=valid_outputs[0].output,
                arbitration_method="single_model",
                model_outputs=[mo.output.model_dump() for mo in valid_outputs],
                consensus_level=1.0,
                divergence_flags=[]
            )
        
        # 根据策略裁决
        if self.strategy == ArbitrationStrategy.CONSENSUS:
            return self._consensus_arbitration(valid_outputs)
        elif self.strategy == ArbitrationStrategy.CONFIDENCE_WEIGHTED:
            return self._confidence_weighted_arbitration(valid_outputs)
        elif self.strategy == ArbitrationStrategy.STRICT:
            return self._strict_arbitration(valid_outputs)
        else:
            return self._consensus_arbitration(valid_outputs)
    
    def _consensus_arbitration(
        self,
        model_outputs: List[ModelOutput]
    ) -> ArbitrationResult:
        """多数投票裁决"""
        outputs = [mo.output for mo in model_outputs]
        
        # 合并风险标记（去重）
        all_risks = []
        risk_signatures = set()
        for o in outputs:
            for r in o.risk_flags:
                sig = f"{r.category}:{r.severity}"
                if sig not in risk_signatures:
                    risk_signatures.add(sig)
                    all_risks.append(r)
        
        # 合并 unknowns（去重）
        all_unknowns = list(set(u for o in outputs for u in o.unknowns))
        
        # 合并 assumptions（去重）
        all_assumptions = list(set(a for o in outputs for a in o.assumptions))
        
        # 合并 recommended_checks（按优先级排序）
        all_checks = []
        check_signatures = set()
        for o in outputs:
            for c in o.recommended_checks:
                sig = f"{c.check_type}:{c.reason}"
                if sig not in check_signatures:
                    check_signatures.add(sig)
                    all_checks.append(c)
        all_checks.sort(key=lambda x: x.priority)
        
        # 合并 summary（简单拼接）
        # 简化：选择置信度最高的summary
        best_summary = max(outputs, key=lambda x: x.confidence).summary
        
        # 计算平均置信度，但降低分歧惩罚
        confidences = [o.confidence for o in outputs]
        avg_confidence = statistics.mean(confidences)
        
        # 计算一致度
        consensus_level = self._calculate_consensus(outputs)
        
        # 如果一致度低，降低最终置信度
        if consensus_level < 0.5:
            final_confidence = avg_confidence * 0.7
            divergence_flags = ["low_consensus"]
        else:
            final_confidence = avg_confidence
            divergence_flags = []
        
        final_output = AIAnalysisOutput(
            summary=best_summary,
            risk_flags=all_risks,
            assumptions=all_assumptions,
            unknowns=all_unknowns,
            recommended_checks=all_checks,
            confidence=round(min(final_confidence, 1.0), 4)
        )
        
        return ArbitrationResult(
            final_output=final_output,
            arbitration_method="consensus",
            model_outputs=[mo.output.model_dump() for mo in model_outputs],
            consensus_level=round(consensus_level, 4),
            divergence_flags=divergence_flags
        )
    
    def _confidence_weighted_arbitration(
        self,
        model_outputs: List[ModelOutput]
    ) -> ArbitrationResult:
        """置信度加权裁决"""
        # 简化：与 consensus 类似，但按置信度加权
        # TODO: 实现完整的置信度加权逻辑
        return self._consensus_arbitration(model_outputs)
    
    def _strict_arbitration(
        self,
        model_outputs: List[ModelOutput]
    ) -> ArbitrationResult:
        """严格一致裁决"""
        outputs = [mo.output for mo in model_outputs]
        
        # 检查置信度是否一致
        confidences = [o.confidence for o in outputs]
        conf_range = max(confidences) - min(confidences)
        
        # 简化：如果置信度差异大，标记分歧
        divergence_flags = []
        if conf_range > 0.3:
            divergence_flags.append("confidence_divergence")
        
        result = self._consensus_arbitration(model_outputs)
        result.divergence_flags = divergence_flags
        
        if divergence_flags:
            # 降低置信度
            result.final_output.confidence *= 0.6
        
        return result
    
    def _calculate_consensus(self, outputs: List[AIAnalysisOutput]) -> float:
        """计算模型间一致程度"""
        if len(outputs) < 2:
            return 1.0
        
        # 基于置信度差异计算一致度
        confidences = [o.confidence for o in outputs]
        conf_std = statistics.stdev(confidences) if len(confidences) > 1 else 0
        
        # 标准差越小，一致度越高
        # 映射到 0-1
        consensus = max(0, 1 - conf_std)
        
        return consensus
    
    def _get_confidence_level(self, confidence: float) -> ConfidenceLevel:
        """将数值转为等级"""
        if confidence >= 0.8:
            return ConfidenceLevel.HIGH
        elif confidence >= 0.5:
            return ConfidenceLevel.MEDIUM
        return ConfidenceLevel.LOW


def analyze_with_arbitration(
    facts: Dict[str, Any],
    models: List[str] = None,
    strategy: str = "consensus"
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    便捷的裁决分析接口
    
    Args:
        facts: 事实数据字典
        models: 模型列表
        strategy: 裁决策略
    
    Returns:
        (分析结果, 追溯记录)
    """
    facts_input = FundFactsInput(**facts)
    
    arbitrator = Arbitrator(
        models=models,
        strategy=ArbitrationStrategy(strategy)
    )
    
    output, trace = arbitrator.arbitrate(facts_input)
    
    return output.model_dump(), trace.model_dump()
