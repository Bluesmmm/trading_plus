"""
AI 分析器单元测试
"""

import pytest
import json
from datetime import datetime
from ai.analyzer import FundAnalyzer, analyze_fund
from ai.schema import FundFactsInput, AIAnalysisOutput


class TestFundAnalyzer:
    """测试基金分析器"""
    
    def setup_method(self):
        """每个测试前创建分析器"""
        self.analyzer = FundAnalyzer(model_name="test-model")
    
    def test_input_hash_consistency(self):
        """测试输入哈希一致性"""
        facts = {
            "fund_code": "000001",
            "fund_name": "测试基金",
            "nav": 1.2345,
            "data_source": "test",
            "last_updated_at": datetime.now()
        }
        
        hash1 = self.analyzer._compute_input_hash(facts)
        hash2 = self.analyzer._compute_input_hash(facts)
        
        # 相同输入应该产生相同哈希
        assert hash1 == hash2
        assert len(hash1) == 16
    
    def test_input_hash_uniqueness(self):
        """测试输入哈希唯一性"""
        facts1 = {
            "fund_code": "000001",
            "data_source": "test",
            "last_updated_at": datetime.now()
        }
        facts2 = {
            "fund_code": "000002",
            "data_source": "test",
            "last_updated_at": datetime.now()
        }
        
        hash1 = self.analyzer._compute_input_hash(facts1)
        hash2 = self.analyzer._compute_input_hash(facts2)
        
        # 不同输入应该产生不同哈希
        assert hash1 != hash2
    
    def test_build_prompt(self):
        """测试提示词构建"""
        facts = FundFactsInput(
            fund_code="000001",
            fund_name="测试基金",
            nav=1.2345,
            nav_date="2024-01-15",
            data_source="test_source",
            last_updated_at=datetime.now(),
            fund_type="股票型"
        )
        
        prompt = self.analyzer._build_prompt(facts)
        
        # 验证提示词包含关键信息
        assert "000001" in prompt
        assert "测试基金" in prompt
        assert "1.2345" in prompt
        assert "test_source" in prompt
        assert "JSON" in prompt
        assert "买入" not in prompt or "不" in prompt  # 确认禁止买入建议
    
    def test_parse_model_output_valid(self):
        """测试解析有效模型输出"""
        valid_json = json.dumps({
            "summary": "测试摘要",
            "confidence": 0.75,
            "risk_flags": [],
            "assumptions": [],
            "unknowns": [],
            "recommended_checks": []
        })
        
        result = self.analyzer._parse_model_output(valid_json)
        assert isinstance(result, AIAnalysisOutput)
        assert result.summary == "测试摘要"
        assert result.confidence == 0.75
    
    def test_parse_model_output_with_markdown(self):
        """测试解析带 markdown 的模型输出"""
        markdown_json = "```json\n" + json.dumps({
            "summary": "测试",
            "confidence": 0.8,
            "risk_flags": [],
            "assumptions": [],
            "unknowns": [],
            "recommended_checks": []
        }) + "\n```"
        
        result = self.analyzer._parse_model_output(markdown_json)
        assert result.summary == "测试"
        assert result.confidence == 0.8
    
    def test_parse_model_output_invalid(self):
        """测试解析无效模型输出"""
        invalid_output = "这不是有效的 JSON"
        
        with pytest.raises(ValueError) as exc_info:
            self.analyzer._parse_model_output(invalid_output)
        
        assert "不是合法 JSON" in str(exc_info.value)
    
    def test_get_confidence_level(self):
        """测试置信度等级转换"""
        assert self.analyzer._get_confidence_level(0.9).value == "high"
        assert self.analyzer._get_confidence_level(0.8).value == "high"
        assert self.analyzer._get_confidence_level(0.7).value == "medium"
        assert self.analyzer._get_confidence_level(0.5).value == "medium"
        assert self.analyzer._get_confidence_level(0.4).value == "low"
        assert self.analyzer._get_confidence_level(0.0).value == "low"
    
    def test_analyze_returns_traceability(self):
        """测试分析返回追溯性记录"""
        facts = FundFactsInput(
            fund_code="000001",
            fund_name="测试基金",
            data_source="test",
            last_updated_at=datetime.now()
        )
        
        output, trace = self.analyzer.analyze(facts, use_cache=False)
        
        # 验证输出
        assert isinstance(output, AIAnalysisOutput)
        assert 0 <= output.confidence <= 1
        
        # 验证追溯记录
        assert trace.fund_code == "000001"
        assert trace.model_name == "test-model"
        assert trace.prompt_version == "1.0.0"
        assert trace.input_hash is not None
        assert trace.analysis_id.startswith("ana_")
    
    def test_cache_functionality(self):
        """测试缓存功能"""
        facts = FundFactsInput(
            fund_code="000001",
            fund_name="测试基金",
            data_source="test",
            last_updated_at=datetime.now()
        )
        
        # 第一次分析
        output1, trace1 = self.analyzer.analyze(facts, use_cache=True)
        assert trace1.cache_hit == False
        
        # 第二次分析（应该命中缓存）
        output2, trace2 = self.analyzer.analyze(facts, use_cache=True)
        assert trace2.cache_hit == True
        
        # 输出应该相同
        assert output1.summary == output2.summary


class TestAnalyzeFund:
    """测试便捷接口"""
    
    def test_analyze_fund_interface(self):
        """测试便捷接口"""
        facts = {
            "fund_code": "000001",
            "fund_name": "测试基金",
            "data_source": "test",
            "last_updated_at": datetime.now()
        }
        
        output, trace = analyze_fund(facts)
        
        assert "summary" in output
        assert "confidence" in output
        assert "analysis_id" in trace
        assert trace["fund_code"] == "000001"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
