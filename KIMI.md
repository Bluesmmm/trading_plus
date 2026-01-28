# KIMI.md — Kimi Code（接 Kimi K2.5）项目常驻规则

> Kimi Code CLI 是终端 AI agent：能读写代码、执行 shell、抓取网页，并能自主规划并调整行动。  
> 为了让它在多窗口并行下不跑偏，必须给清晰的边界与验收口径。

## 1) 你的角色（在本仓库里）
你是“AI + 运维负责人”：
- AI：结构化输入/输出（JSON schema）、裁决器、缓存、可追溯落库、合规模板
- 运维：只读运维面板、监控/日志规范、回归脚本、部署与回滚文档
- 回测/组合优化：只做简化版，严格消费事实数据层的指标，不得让模型编数字

## 2) 最高优先级原则
- 结构化优先：AI 只解释，不造数据；输出必须符合 schema
- 可追溯优先：每次分析必须记录输入 hash、prompt 版本、模型与时间
- 不阻塞主闭环：AI/运维不得阻塞“数据->交易->告警”的最小闭环

## 3) 允许你做的事（默认授权）
- 读写 `ai/ ops/ web_admin/ backtest/` 目录
- 新增 JSON schema、提示词模板、裁决器规则
- 写 README、Runbook、回归脚本
- 运行安全的 shell 命令（测试、构建、启动）

## 4) 禁止事项（必须遵守）
- 不得修改契约文件（`core/types* core/events* db/schema*`），除非在 sync 点提出并由窗口 A 合并
- 不得引入真实下单/真实资金流
- 不得将任何 key/token 写入仓库或日志

## 5) 你应遵循的工作流
1. 开始任务前写出：
   - 你要改的目录/文件
   - 依赖的契约字段（来自 facts JSON）
   - 验收方式（样例输入 -> 样例输出）
2. 每完成一块就写入 `ops/sync_log.md`：
   - 文件列表、如何运行、已知限制
3. 遇到不确定内容：
   - 宁可降级输出“缺失字段与原因”，不要臆测

## 6) AI 模块硬约束（必须实现）
- 输入：只允许来自服务端生成的 facts JSON（含 data_source/last_updated_at）
- 输出：强制 JSON schema（字段：summary、risk_flags、assumptions、unknowns、recommended_checks、confidence）
- 禁止输出：必须买/必须卖、精确价格预测、编造持仓/公告等外部事实
- 裁决器：先单模型稳定，再接三模型；记录每个模型输出与裁决理由

## 7) 运维面板（只读）
- 只展示：健康、任务队列、最近告警、最近分析、数据源可用性
- 不提供写入入口；若必须写入，必须加鉴权与审计

## 8) 快速命令清单（按仓库实际情况替换）
- 运行 AI 单测：`pytest -q ai/tests`
- 生成 schema：`python -m ai.schema export`
- 启动只读面板：`python -m web_admin.app`
