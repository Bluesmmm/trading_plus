#!/usr/bin/env python3
"""
骨架验证脚本

检查项目关键文件是否存在并可导入
"""

import os
import sys
from pathlib import Path


# 颜色输出
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"


def check_file(path: Path, description: str) -> bool:
    """检查文件是否存在"""
    if path.exists():
        print(f"{GREEN}✓{RESET} {description}: {path}")
        return True
    else:
        print(f"{RED}✗{RESET} {description}: {path} (不存在)")
        return False


def check_import(module: str, description: str) -> bool:
    """检查模块是否可导入"""
    try:
        __import__(module)
        print(f"{GREEN}✓{RESET} {description}: {module}")
        return True
    except Exception as e:
        print(f"{RED}✗{RESET} {description}: {module} ({e})")
        return False


def main():
    """主验证流程"""
    print("=" * 60)
    print("基金交易系统 - 骨架验证")
    print("=" * 60)

    project_root = Path(__file__).parent.parent
    all_ok = True

    # 检查配置文件
    print("\n{YELLOW}配置文件{RESET}".format(YELLOW=YELLOW, RESET=RESET))
    all_ok &= check_file(project_root / "pyproject.toml", "依赖配置")
    all_ok &= check_file(project_root / ".env.example", "环境变量示例")
    all_ok &= check_file(project_root / "README.md", "项目说明")

    # 检查核心模块
    print("\n{YELLOW}核心模块{RESET}".format(YELLOW=YELLOW, RESET=RESET))
    all_ok &= check_file(project_root / "core" / "types.py", "核心类型契约")
    all_ok &= check_file(project_root / "core" / "events.py", "事件层")
    all_ok &= check_file(project_root / "core" / "alerts.py", "告警引擎")

    # 检查适配器
    print("\n{YELLOW}数据适配器{RESET}".format(YELLOW=YELLOW, RESET=RESET))
    all_ok &= check_file(project_root / "adapters" / "base.py", "适配器基类")
    all_ok &= check_file(project_root / "adapters" / "eastmoney.py", "东方财富适配器")

    # 检查 Bot
    print("\n{YELLOW}Bot 主流程{RESET}".format(YELLOW=YELLOW, RESET=RESET))
    all_ok &= check_file(project_root / "bot" / "main.py", "Bot 主程序")

    # 检查任务调度
    print("\n{YELLOW}任务调度{RESET}".format(YELLOW=YELLOW, RESET=RESET))
    all_ok &= check_file(project_root / "jobs" / "scheduler.py", "调度器")

    # 检查数据库
    print("\n{YELLOW}数据库{RESET}".format(YELLOW=YELLOW, RESET=RESET))
    all_ok &= check_file(project_root / "db" / "schema.sql", "数据库 Schema")

    # 检查测试
    print("\n{YELLOW}测试{RESET}".format(YELLOW=YELLOW, RESET=RESET))
    all_ok &= check_file(project_root / "tests" / "test_core.py", "核心测试")

    # 检查同步日志
    print("\n{YELLOW}同步日志{RESET}".format(YELLOW=YELLOW, RESET=RESET))
    all_ok &= check_file(project_root / "ops" / "sync_log.md", "同步日志")

    # 尝试导入关键模块
    print("\n{YELLOW}模块导入测试{RESET}".format(YELLOW=YELLOW, RESET=RESET))
    sys.path.insert(0, str(project_root))
    try:
        import core.types
        import core.events
        import core.alerts
        print(f"{GREEN}✓{RESET} 所有核心模块导入成功")
    except ImportError as e:
        print(f"{YELLOW}⚠{RESET} 模块导入需要先安装依赖: {e}")
        print(f"  运行: pip install -e .")

    # 总结
    print("\n" + "=" * 60)
    if all_ok:
        print(f"{GREEN}骨架验证通过 ✓{RESET}")
        return 0
    else:
        print(f"{RED}骨架验证失败 ✗{RESET}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
