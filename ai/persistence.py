"""
AI 分析可追溯性持久化

将分析记录落库，支持审计、回溯、质量评估

数据库表设计（由窗口 A 在契约文件中最终确认）：

```sql
CREATE TABLE ai_analysis_logs (
    -- 主键
    analysis_id VARCHAR(32) PRIMARY KEY,
    created_at TIMESTAMP NOT NULL,
    
    -- 输入信息（追溯核心）
    input_hash VARCHAR(16) NOT NULL,
    fund_code VARCHAR(20) NOT NULL,
    facts_snapshot JSONB NOT NULL,
    
    -- 模型信息
    model_name VARCHAR(50) NOT NULL,
    model_version VARCHAR(20) NOT NULL,
    prompt_version VARCHAR(20) NOT NULL,
    
    -- 输出结果
    output_json JSONB NOT NULL,
    confidence_level VARCHAR(10) NOT NULL,  -- high/medium/low
    
    -- 裁决信息（多模型时用）
    is_arbitrated BOOLEAN DEFAULT FALSE,
    arbitration_method VARCHAR(50),
    model_outputs JSONB,  -- 各模型原始输出数组
    
    -- 性能指标
    latency_ms INTEGER NOT NULL,
    cache_hit BOOLEAN DEFAULT FALSE,
    
    -- 索引
    INDEX idx_fund_code_created (fund_code, created_at),
    INDEX idx_input_hash (input_hash),
    INDEX idx_created_at (created_at)
);
```
"""

import json
import sqlite3
from typing import Dict, Any, List, Optional
from datetime import datetime
from pathlib import Path

from ai.schema import AnalysisTraceability


class AnalysisPersistence:
    """
    分析记录持久化（SQLite 实现，可迁移到 PostgreSQL）
    """
    
    def __init__(self, db_path: str = "db/ai_analysis.db"):
        self.db_path = db_path
        self._ensure_db()
    
    def _ensure_db(self):
        """确保数据库和表存在"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_analysis_logs (
                analysis_id TEXT PRIMARY KEY,
                created_at TIMESTAMP NOT NULL,
                input_hash TEXT NOT NULL,
                fund_code TEXT NOT NULL,
                facts_snapshot TEXT NOT NULL,  -- JSON
                model_name TEXT NOT NULL,
                model_version TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                output_json TEXT NOT NULL,  -- JSON
                confidence_level TEXT NOT NULL,
                is_arbitrated BOOLEAN DEFAULT 0,
                arbitration_method TEXT,
                model_outputs TEXT,  -- JSON
                latency_ms INTEGER NOT NULL,
                cache_hit BOOLEAN DEFAULT 0
            )
        """)
        
        # 创建索引
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_fund_code_created 
            ON ai_analysis_logs(fund_code, created_at)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_input_hash 
            ON ai_analysis_logs(input_hash)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_created_at 
            ON ai_analysis_logs(created_at)
        """)
        
        conn.commit()
        conn.close()
    
    def save(self, trace: AnalysisTraceability) -> bool:
        """
        保存分析记录
        
        Args:
            trace: 可追溯性记录
            
        Returns:
            是否成功
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT OR REPLACE INTO ai_analysis_logs (
                    analysis_id, created_at, input_hash, fund_code, facts_snapshot,
                    model_name, model_version, prompt_version, output_json,
                    confidence_level, is_arbitrated, arbitration_method, model_outputs,
                    latency_ms, cache_hit
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trace.analysis_id,
                trace.created_at.isoformat(),
                trace.input_hash,
                trace.fund_code,
                json.dumps(trace.facts_snapshot, default=str),
                trace.model_name,
                trace.model_version,
                trace.prompt_version,
                json.dumps(trace.output_json, default=str),
                trace.confidence_level.value,
                trace.is_arbitrated,
                trace.arbitration_method,
                json.dumps(trace.model_outputs, default=str) if trace.model_outputs else None,
                trace.latency_ms,
                trace.cache_hit
            ))
            
            conn.commit()
            conn.close()
            return True
            
        except Exception as e:
            print(f"[ERROR] 保存分析记录失败: {e}")
            return False
    
    def get_by_id(self, analysis_id: str) -> Optional[Dict[str, Any]]:
        """根据 ID 获取分析记录"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM ai_analysis_logs WHERE analysis_id = ?
        """, (analysis_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
            
        return self._row_to_dict(row, cursor)
    
    def get_by_fund(
        self, 
        fund_code: str, 
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """获取某基金的最近分析记录"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM ai_analysis_logs 
            WHERE fund_code = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (fund_code, limit))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [self._row_to_dict(row, cursor) for row in rows]
    
    def get_by_input_hash(self, input_hash: str) -> List[Dict[str, Any]]:
        """根据输入哈希获取记录（用于检查重复分析）"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM ai_analysis_logs 
            WHERE input_hash = ?
            ORDER BY created_at DESC
        """, (input_hash,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [self._row_to_dict(row, cursor) for row in rows]
    
    def get_recent(
        self, 
        hours: int = 24, 
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """获取最近 N 小时的分析记录"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM ai_analysis_logs 
            WHERE created_at >= datetime('now', '-' || ? || ' hours')
            ORDER BY created_at DESC
            LIMIT ?
        """, (hours, limit))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [self._row_to_dict(row, cursor) for row in rows]
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计分析指标（用于运维面板）"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 总记录数
        cursor.execute("SELECT COUNT(*) FROM ai_analysis_logs")
        total_count = cursor.fetchone()[0]
        
        # 今日记录数
        cursor.execute("""
            SELECT COUNT(*) FROM ai_analysis_logs 
            WHERE date(created_at) = date('now')
        """)
        today_count = cursor.fetchone()[0]
        
        # 平均耗时
        cursor.execute("SELECT AVG(latency_ms) FROM ai_analysis_logs")
        avg_latency = cursor.fetchone()[0] or 0
        
        # 置信度分布
        cursor.execute("""
            SELECT confidence_level, COUNT(*) 
            FROM ai_analysis_logs 
            GROUP BY confidence_level
        """)
        confidence_dist = {row[0]: row[1] for row in cursor.fetchall()}
        
        # 缓存命中率
        cursor.execute("""
            SELECT 
                SUM(CASE WHEN cache_hit = 1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*)
            FROM ai_analysis_logs
        """)
        cache_hit_rate = cursor.fetchone()[0] or 0
        
        conn.close()
        
        return {
            "total_count": total_count,
            "today_count": today_count,
            "avg_latency_ms": round(avg_latency, 2),
            "confidence_distribution": confidence_dist,
            "cache_hit_rate_percent": round(cache_hit_rate, 2)
        }
    
    def _row_to_dict(self, row: tuple, cursor: sqlite3.Cursor) -> Dict[str, Any]:
        """将数据库行转换为字典"""
        columns = [desc[0] for desc in cursor.description]
        result = dict(zip(columns, row))
        
        # 解析 JSON 字段
        for field in ["facts_snapshot", "output_json", "model_outputs"]:
            if result.get(field):
                try:
                    result[field] = json.loads(result[field])
                except json.JSONDecodeError:
                    pass
        
        return result


# 全局持久化实例
_persistence: Optional[AnalysisPersistence] = None


def get_persistence() -> AnalysisPersistence:
    """获取全局持久化实例"""
    global _persistence
    if _persistence is None:
        _persistence = AnalysisPersistence()
    return _persistence


def save_analysis(trace: AnalysisTraceability) -> bool:
    """便捷接口：保存分析记录"""
    return get_persistence().save(trace)
