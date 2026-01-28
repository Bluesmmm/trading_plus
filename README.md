# 基金交易系统（Telegram 核心）

> 基于 Telegram Bot 的基金/ETF 模拟交易与预警分析系统

## 功能特性

- **数据闭环**: 东方财富/天天基金网净值数据拉取 -> 入库 -> 查询
- **模拟交易**: 买入/卖出/定投 -> 事件落库（幂等）-> T+1 结算 -> 持仓可重建
- **预警系统**: 阈值/回撤/波动率预警 -> 去重 + 冷却窗口 -> Telegram 推送
- **AI 分析**: 三模型裁决器 + 结构化输出（开发中）

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
# 或
pip install -e .
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 填入 DATABASE_URL 和 TELEGRAM_BOT_TOKEN
```

### 3. 初始化数据库

```bash
# 创建数据库
createdb trading_plus

# 执行 schema
psql -d trading_plus -f db/schema.sql
```

### 4. 运行 Bot

```bash
python -m bot.main
```

### 5. 运行调度器

```bash
python -m jobs.scheduler
```

## Bot 命令

| 命令 | 说明 | 示例 |
|------|------|------|
| `/start` | 欢迎消息 | `/start` |
| `/nav <code> [n]` | 查询净值走势 | `/nav 000001 7` |
| `/buy_sim <code> <amount>` | 模拟买入 | `/buy_sim 000001 1000` |
| `/settle [trade_id]` | 结算交易 | `/settle` |
| `/alert_add <code> <type> <threshold>` | 添加预警 | `/alert_add 000001 drawdown 10` |
| `/alert_list` | 列出预警规则 | `/alert_list` |

## 项目结构

```
trading_plus/
├── adapters/        # 数据源适配器
├── bot/            # Telegram Bot 主流程
├── core/           # 核心类型和领域逻辑
├── db/             # 数据库 schema 和迁移
├── jobs/           # 任务调度器
├── ai/             # AI 分析模块（Kimi 负责）
├── ops/            # 运维文档和同步日志
└── tests/          # 测试用例
```

## 开发

### 运行测试

```bash
pytest -q
```

### 代码格式化

```bash
ruff check .
ruff format .
```

## 免责声明

⚠️ 本系统仅用于模拟交易，不提供任何投资建议。所有交易均为模拟，不涉及真实资金。

## 许可证

MIT License
