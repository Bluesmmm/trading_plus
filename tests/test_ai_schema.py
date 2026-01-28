"""
AI Schema 单元测试
"""

import pytest
from datetime import datetime
from ai.schema import (
    AIAnalysisOutput,
    FundFactsInput,
    AnalysisTraceability,
    ConfidenceLevel,
    RiskFlag,
    RecommendedCheck,
    get_output_schema,
    validate_facts_input,
    validate_analysis_output
)


class TestAIAnalysisOutput:
    """测试 AI 分析输出 Schema"""
    
    def test_valid_output(self):
        """测试有效输出"""
        output = AIAnalysisOutput(
            summary="这是一个测试分析摘要",
            risk_flags=[
                RiskFlag(
                    severity="medium",
                    category="liquidity",
                    description="流动性风险描述",
                    source_field="fund_scale"
                )
            ],
            assumptions=["假设数据准确"],
            unknowns=["缺乏最新季报"],
            recommended_checks=[
                RecommendedCheck(
                    check_type="查看季报",
                    reason="确认持仓变化",
                    priority=2
                )
            ],
            confidence=0.75
        )
        
        assert output.confidence == 0.75
        assert len(output.risk_flags) == 1
        assert output.risk_flags[0].severity == "medium"
    
    def test_confidence_range(self):
        """测试置信度范围限制"""
        # 有效范围
        AIAnalysisOutput(summary="test", confidence=0.0)
        AIAnalysisOutput(summary="test", confidence=1.0)
        AIAnalysisOutput(summary="test", confidence=0.5)
        
        # 超出范围应该失败
        with pytest.raises(ValueError):
            AIAnalysisOutput(summary="test", confidence=-0.1)
        
        with pytest.raises(ValueError):
            AIAnalysisOutput(summary="test", confidence=1.1)
    
    def test_to_json(self):
        """测试 JSON 序列化"""
        output = AIAnalysisOutput(
            summary="测试",
            confidence=0.8
        )
        
        json_data = output.model_dump()
        assert json_data["summary"] == "测试"
        assert json_data["confidence"] == 0.8
        assert json_data["risk_flags"] == []


class TestFundFactsInput:
    """测试基金事实数据输入 Schema"""
    
    def test_valid_input(self):
        """测试有效输入"""
        now = datetime.now()
        facts = FundFactsInput(
            fund_code="000001",
            fund_name="测试基金",
            nav=1.2345,
            nav_date="2024-01-15",
            data_source="test_source",
            last_updated_at=now,
            fund_type="股票型",
            fund_scale=50.0
        )
        
        assert facts.fund_code == "000001"
        assert facts.data_source == "test_source"
        assert facts.last_updated_at == now
    
    def test_required_fields(self):
        """测试必填字段"""
        now = datetime.now()
        
        # 缺少必填字段应该失败
        with pytest.raises(ValueError):
            FundFactsInput(
                fund_name="测试基金",  # 缺少 fund_code
                data_source="test",
                last_updated_at=now
            )
        
        with pytest.raises(ValueError):
            FundFactsInput(
                fund_code="000001",
                data_source="test",
                # 缺少 last_updated_at
            )
    
    def test_optional_fields(self):
        """测试可选字段"""
        now = datetime.now()
        facts = FundFactsInput(
            fund_code="000001",
            fund_name="测试基金",
            data_source="test",
            last_updated_at=now
            # 省略所有可选字段
        )
        
        assert facts.nav is None
        assert facts.fund_scale is None


class TestAnalysisTraceability:
    """测试可追溯性记录 Schema"""
    
    def test_trace_creation(self):
        """测试创建追溯记录"""
        now = datetime.now()
        trace = AnalysisTraceability(
            analysis_id="test_001",
            created_at=now,
            input_hash="abc123",
            fund_code="000001",
            facts_snapshot={"nav": 1.23},
            model_name="test-model",
            model_version="1.0",
            prompt_version="1.0.0",
            output_json={"summary": "test"},
            confidence_level=ConfidenceLevel.HIGH,
            latency_ms=100
        )
        
        assert trace.analysis_id == "test_001"
        assert trace.is_arbitrated == False
        assert trace.cache_hit == False


class TestSchemaUtils:
    """测试 Schema 工具函数"""
    
    def test_get_output_schema(self):
        """测试获取输出 Schema"""
        schema = get_output_schema()
        assert "properties" in schema
        assert "summary" in schema["properties"]
        assert "confidence" in schema["properties"]
    
    def test_validate_facts_input(self):
        """测试验证输入数据"""
        now = datetime.now()
        data = {
            "fund_code": "000001",
            "fund_name": "测试基金",
            "data_source": "test",
            "last_updated_at": now
        }
        
        result = validate_facts_input(data)
        assert result.fund_code == "000001"
    
    def test_validate_analysis_output(self):
        """测试验证输出数据"""
        data = {
            "summary": "测试摘要",
            "confidence": 0.75,
            "risk_flags": []
        }
        
        result = validate_analysis_output(data)
        assert result.confidence == 0.75


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
