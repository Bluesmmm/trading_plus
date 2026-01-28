"""
只读运维面板

提供系统健康、任务队列、告警、AI 分析的可视化展示
"""

from web_admin.app import app, get_health_status, get_ai_stats

__all__ = ["app", "get_health_status", "get_ai_stats"]
