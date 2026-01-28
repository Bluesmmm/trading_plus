"""
只读运维面板

功能（来自 KIMI.md #7）：
- 只展示：健康、任务队列、最近告警、最近分析、数据源可用性
- 不提供写入入口

实现：使用 Flask 提供轻量级 Web 界面
"""

import os
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, Any, List
from flask import Flask, jsonify, render_template_string

app = Flask(__name__)

# 配置
DB_PATH = os.getenv("DB_PATH", "db/fund_system.db")
AI_DB_PATH = os.getenv("AI_DB_PATH", "db/ai_analysis.db")


# ============== HTML 模板 ==============

DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>基金交易系统 - 运维面板</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f5f5;
            color: #333;
            line-height: 1.6;
        }
        .header {
            background: #1a1a2e;
            color: white;
            padding: 1rem 2rem;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .header h1 { font-size: 1.5rem; }
        .header .subtitle { color: #888; font-size: 0.875rem; }
        .container { max-width: 1400px; margin: 0 auto; padding: 2rem; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1.5rem; }
        .card {
            background: white;
            border-radius: 8px;
            padding: 1.5rem;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }
        .card h2 {
            font-size: 1rem;
            color: #666;
            margin-bottom: 1rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .status { display: flex; align-items: center; gap: 0.5rem; }
        .status-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            display: inline-block;
        }
        .status-ok { background: #10b981; }
        .status-warn { background: #f59e0b; }
        .status-error { background: #ef4444; }
        .metric {
            display: flex;
            justify-content: space-between;
            padding: 0.75rem 0;
            border-bottom: 1px solid #eee;
        }
        .metric:last-child { border-bottom: none; }
        .metric-label { color: #666; }
        .metric-value { font-weight: 600; }
        .table-container { overflow-x: auto; }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.875rem;
        }
        th, td {
            text-align: left;
            padding: 0.75rem;
            border-bottom: 1px solid #eee;
        }
        th { color: #666; font-weight: 500; }
        .badge {
            display: inline-block;
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 500;
        }
        .badge-high { background: #fee2e2; color: #991b1b; }
        .badge-medium { background: #fef3c7; color: #92400e; }
        .badge-low { background: #dbeafe; color: #1e40af; }
        .timestamp { color: #888; font-size: 0.75rem; }
        .empty-state { color: #888; text-align: center; padding: 2rem; }
        footer {
            text-align: center;
            padding: 2rem;
            color: #888;
            font-size: 0.875rem;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>基金交易系统运维面板</h1>
        <div class="subtitle">只读视图 | 最后更新: {{ now }}</div>
    </div>
    
    <div class="container">
        <div class="grid">
            <!-- 健康状态 -->
            <div class="card">
                <h2>系统健康</h2>
                <div class="status">
                    <span class="status-dot status-{{ health.status }}"></span>
                    <span>{{ health.message }}</span>
                </div>
                <div style="margin-top: 1rem;">
                    {% for check in health.checks %}
                    <div class="metric">
                        <span class="metric-label">{{ check.name }}</span>
                        <span class="status-dot status-{{ check.status }}"></span>
                    </div>
                    {% endfor %}
                </div>
            </div>
            
            <!-- 数据源状态 -->
            <div class="card">
                <h2>数据源可用性</h2>
                {% for source in data_sources %}
                <div class="metric">
                    <span class="metric-label">{{ source.name }}</span>
                    <span>
                        <span class="status-dot status-{{ source.status }}"></span>
                        <span style="font-size: 0.75rem; color: #888;">{{ source.last_update }}</span>
                    </span>
                </div>
                {% endfor %}
            </div>
            
            <!-- AI 分析统计 -->
            <div class="card">
                <h2>AI 分析统计</h2>
                <div class="metric">
                    <span class="metric-label">总分析次数</span>
                    <span class="metric-value">{{ ai_stats.total_count }}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">今日分析</span>
                    <span class="metric-value">{{ ai_stats.today_count }}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">平均耗时</span>
                    <span class="metric-value">{{ ai_stats.avg_latency_ms }}ms</span>
                </div>
                <div class="metric">
                    <span class="metric-label">缓存命中率</span>
                    <span class="metric-value">{{ ai_stats.cache_hit_rate_percent }}%</span>
                </div>
            </div>
            
            <!-- 任务队列状态 -->
            <div class="card">
                <h2>任务队列</h2>
                <div class="metric">
                    <span class="metric-label">待执行</span>
                    <span class="metric-value">{{ tasks.pending }}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">执行中</span>
                    <span class="metric-value">{{ tasks.running }}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">失败（24h）</span>
                    <span class="metric-value" style="color: {% if tasks.failed > 0 %}#ef4444{% else %}inherit{% endif %}">
                        {{ tasks.failed }}
                    </span>
                </div>
                <div class="metric">
                    <span class="metric-label">成功（24h）</span>
                    <span class="metric-value" style="color: #10b981;">{{ tasks.succeeded }}</span>
                </div>
            </div>
        </div>
        
        <!-- 最近告警 -->
        <div class="card" style="margin-top: 1.5rem;">
            <h2>最近告警</h2>
            <div class="table-container">
                <table>
                    <thead>
                        <tr>
                            <th>时间</th>
                            <th>基金</th>
                            <th>规则</th>
                            <th>触发值</th>
                            <th>置信度</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for alert in recent_alerts %}
                        <tr>
                            <td class="timestamp">{{ alert.created_at }}</td>
                            <td>{{ alert.fund_code }}</td>
                            <td>{{ alert.rule_name }}</td>
                            <td>{{ alert.trigger_value }}</td>
                            <td><span class="badge badge-{{ alert.severity }}">{{ alert.severity }}</span></td>
                        </tr>
                        {% else %}
                        <tr>
                            <td colspan="5" class="empty-state">最近 24 小时无告警</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
        
        <!-- 最近 AI 分析 -->
        <div class="card" style="margin-top: 1.5rem;">
            <h2>最近 AI 分析</h2>
            <div class="table-container">
                <table>
                    <thead>
                        <tr>
                            <th>时间</th>
                            <th>基金</th>
                            <th>模型</th>
                            <th>置信度</th>
                            <th>耗时</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for analysis in recent_analyses %}
                        <tr>
                            <td class="timestamp">{{ analysis.created_at }}</td>
                            <td>{{ analysis.fund_code }}</td>
                            <td>{{ analysis.model_name }}</td>
                            <td><span class="badge badge-{{ analysis.confidence_level }}">{{ analysis.confidence_level }}</span></td>
                            <td>{{ analysis.latency_ms }}ms</td>
                        </tr>
                        {% else %}
                        <tr>
                            <td colspan="5" class="empty-state">暂无分析记录</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    
    <footer>
        基金交易系统 v0.1.0 | 只读运维面板
    </footer>
    
    <script>
        // 每 30 秒自动刷新
        setTimeout(() => window.location.reload(), 30000);
    </script>
</body>
</html>
"""


# ============== 数据获取函数 ==============

def get_health_status() -> Dict[str, Any]:
    """获取系统健康状态"""
    checks = []
    overall_status = "ok"
    
    # 检查主数据库
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("SELECT 1")
        conn.close()
        checks.append({"name": "主数据库", "status": "ok"})
    except Exception:
        checks.append({"name": "主数据库", "status": "error"})
        overall_status = "error"
    
    # 检查 AI 数据库
    try:
        conn = sqlite3.connect(AI_DB_PATH)
        conn.execute("SELECT 1")
        conn.close()
        checks.append({"name": "AI 分析数据库", "status": "ok"})
    except Exception:
        checks.append({"name": "AI 分析数据库", "status": "warn"})
        if overall_status == "ok":
            overall_status = "warn"
    
    return {
        "status": overall_status,
        "message": "系统运行正常" if overall_status == "ok" else "部分服务异常",
        "checks": checks
    }


def get_data_sources() -> List[Dict[str, Any]]:
    """获取数据源状态（模拟，实际应从适配器获取）"""
    # TODO: 接入实际数据源适配器状态
    return [
        {"name": "东方财富/天天基金", "status": "ok", "last_update": "10分钟前"},
        {"name": "WSJ 资讯", "status": "ok", "last_update": "5分钟前"},
    ]


def get_ai_stats() -> Dict[str, Any]:
    """获取 AI 分析统计"""
    try:
        from ai.persistence import get_persistence
        return get_persistence().get_stats()
    except Exception:
        return {
            "total_count": 0,
            "today_count": 0,
            "avg_latency_ms": 0,
            "confidence_distribution": {},
            "cache_hit_rate_percent": 0
        }


def get_task_stats() -> Dict[str, int]:
    """获取任务队列统计（模拟，实际应从任务调度器获取）"""
    # TODO: 接入实际任务队列
    return {
        "pending": 0,
        "running": 0,
        "failed": 0,
        "succeeded": 0
    }


def get_recent_alerts(limit: int = 10) -> List[Dict[str, Any]]:
    """获取最近告警"""
    # TODO: 接入实际告警表
    # 从主数据库查询 alerts 表
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT created_at, fund_code, rule_name, trigger_value, severity
            FROM alerts 
            WHERE created_at >= datetime('now', '-1 day')
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
        conn.close()
        
        return [
            {
                "created_at": row[0],
                "fund_code": row[1],
                "rule_name": row[2],
                "trigger_value": row[3],
                "severity": row[4]
            }
            for row in rows
        ]
    except Exception:
        return []


def get_recent_analyses(limit: int = 10) -> List[Dict[str, Any]]:
    """获取最近 AI 分析"""
    try:
        conn = sqlite3.connect(AI_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT created_at, fund_code, model_name, confidence_level, latency_ms
            FROM ai_analysis_logs 
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
        conn.close()
        
        return [
            {
                "created_at": row[0][:19] if row[0] else "",
                "fund_code": row[1],
                "model_name": row[2],
                "confidence_level": row[3],
                "latency_ms": row[4]
            }
            for row in rows
        ]
    except Exception:
        return []


# ============== 路由 ==============

@app.route("/")
def dashboard():
    """主面板页面"""
    return render_template_string(
        DASHBOARD_TEMPLATE,
        now=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        health=get_health_status(),
        data_sources=get_data_sources(),
        ai_stats=get_ai_stats(),
        tasks=get_task_stats(),
        recent_alerts=get_recent_alerts(),
        recent_analyses=get_recent_analyses()
    )


@app.route("/api/health")
def api_health():
    """健康检查 API"""
    return jsonify(get_health_status())


@app.route("/api/stats")
def api_stats():
    """统计信息 API"""
    return jsonify({
        "ai": get_ai_stats(),
        "tasks": get_task_stats()
    })


@app.route("/api/alerts")
def api_alerts():
    """最近告警 API"""
    return jsonify(get_recent_alerts())


@app.route("/api/analyses")
def api_analyses():
    """最近分析 API"""
    return jsonify(get_recent_analyses())


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    debug = os.getenv("DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
