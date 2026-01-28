# 工作日报 - 2026-01-28

> 角色：AI + 运维负责人 (Kimi Code)
> 对应 PLAN.md 窗口 B 职责

---

## 一、今日完成工作

### 1. AI 结构化输出体系 (ai/)

| 文件 | 功能 | 关键设计 |
|------|------|----------|
| `ai/schema.py` | Schema 定义 | `AIAnalysisOutput`(强制 JSON 输出), `FundFactsInput`(含 data_source 追溯字段), `AnalysisTraceability`(完整可追溯落库字段) |
| `ai/analyzer.py` | 单模型分析器 | `FundAnalyzer` 类，输入 SHA-256 哈希计算、内存缓存、强制 JSON 解析、提示词模板约束 |
| `ai/arbitrator.py` | 三模型裁决器 | `Arbitrator` 类，支持 consensus/confidence_weighted/strict 三种裁决策略，记录各模型输出与分歧标记 |
| `ai/persistence.py` | 可追溯落库 | SQLite 实现，预留 PostgreSQL 迁移路径，提供 stats API 供运维面板调用 |
| `ai/prompts/fund_analysis_v1.md` | 提示词模板 | v1.0.0，明确约束：只解释不编造、禁止买卖建议、confidence 计算指南 |

**核心约束落地（KIMI.md #6）：**
- ✅ 输入只允许服务端生成的事实 JSON（含 data_source/last_updated_at）
- ✅ 输出强制符合 JSON schema（summary/risk_flags/assumptions/unknowns/recommended_checks/confidence）
- ✅ 禁止输出：必须买/必须卖、精确价格预测、编造持仓/公告

### 2. 回测与组合优化 (backtest/)

| 文件 | 功能 | 说明 |
|------|------|------|
| `backtest/engine.py` | 回测引擎（简化版） | 基于净值序列模拟交易，计算总收益、年化收益、波动率、最大回撤、夏普比率 |
| `backtest/portfolio.py` | 组合优化（简化版） | 四种配置策略：等权、最小方差、最大夏普、风险平价，输出权重配置建议（不含买卖指令） |

**核心约束落地：**
- ✅ 只消费事实数据层的指标（净值、收益率）
- ✅ 不得让模型编数字
- ✅ 仅用于历史模拟，不提供具体买卖建议

### 3. 只读运维面板 (web_admin/)

| 文件 | 功能 |
|------|------|
| `web_admin/app.py` | Flask 应用，提供：系统健康检查、数据源可用性、AI 分析统计、任务队列状态、最近告警列表、最近 AI 分析列表 |

**设计原则（KIMI.md #7）：**
- ✅ 只读展示，不提供写入入口
- ✅ 30 秒自动刷新
- ✅ API 端点：`/api/health`, `/api/stats`, `/api/alerts`, `/api/analyses`

### 4. 单元测试 (tests/)

| 文件 | 覆盖内容 |
|------|----------|
| `tests/test_ai_schema.py` | Schema 验证、必填/可选字段、JSON 序列化、工具函数 |
| `tests/test_ai_analyzer.py` | 输入哈希一致性、提示词构建、模型输出解析、缓存功能 |
| `tests/test_backtest_engine.py` | 持仓计算、买卖信号、指标计算、便捷接口 |

---

## 二、关键设计决策

### 1. 可追溯性设计
- 每次 AI 分析记录：`analysis_id`, `input_hash`, `facts_snapshot`, `prompt_version`, `model_name`
- 支持输入哈希去重（避免重复分析相同数据）
- 多模型裁决时记录各模型输出和裁决理由

### 2. 缓存策略
- 内存缓存（简单 dict），Key: `fund_code:input_hash`
- 追溯记录标记 `cache_hit`，便于统计命中率

### 3. 裁决策略
| 策略 | 说明 | 适用场景 |
|------|------|----------|
| `consensus` | 多数投票，合并风险标记和 unknowns | 默认策略 |
| `confidence_weighted` | 置信度加权（预留） | 模型可靠性差异大时 |
| `strict` | 必须一致，否则降低置信度 | 高可靠性要求场景 |

### 4. 数据库选型
- 当前：SQLite（零配置，开发友好）
- 预留：PostgreSQL 迁移路径（表结构注释已准备）

---

## 三、阻塞与依赖

### 等待窗口 A (Claude Code)
| 依赖项 | 用途 | 状态 |
|--------|------|------|
| `db/schema*.sql` | 确认 `ai_analysis_logs` 表结构与契约一致 | ⏳ 等待 |
| `core/types*.py` | 确认 Fund/NAV/Trade 类型定义 | ⏳ 等待 |
| `alerts` 表 | 运维面板展示真实告警数据 | ⏳ 等待 |
| `tasks` 表 | 运维面板展示任务队列状态 | ⏳ 等待 |
| 净值数据接口 | 联调回测引擎 | ⏳ 等待 |

### 环境依赖
```bash
# 待安装
pip install pydantic flask pytest
```

### 配置待补充
- Kimi API Key（环境变量或配置文件，不提交到仓库）
- GLM API Key（三模型裁决时使用）

---

## 四、明日工作展望

### 高优先级（阻塞解除后立即进行）
1. **接入真实模型 API**
   - 实现 `FundAnalyzer._call_model()` 的真实调用
   - 支持 Kimi API（优先）和 GLM API
   - 错误处理：超时、限流、格式错误降级

2. **与窗口 A 联调**
   - 验证 `FundFactsInput` 与窗口 A 的数据源输出格式一致
   - 确认 `data_source` 和 `last_updated_at` 字段来源
   - 集成测试：数据 -> AI 分析 -> 落库 -> 运维面板展示

3. **运行单元测试**
   - 安装依赖后运行 `pytest tests/test_ai_*.py tests/test_backtest_*.py`
   - 修复测试失败项

### 中优先级
4. **运维面板增强**
   - 接入真实告警数据（`alerts` 表）
   - 接入真实任务队列（`tasks` 表）
   - 添加数据源健康检查详情

5. **裁决器优化**
   - 实现 `confidence_weighted` 完整逻辑
   - 添加分歧分析（哪些字段不一致）
   - 分歧时自动触发第三模型仲裁

### 低优先级（Nice to have）
6. **性能优化**
   - 缓存持久化（Redis/SQLite）
   - 模型调用并行化优化
   - 大数据量回测性能测试

7. **文档完善**
   - AI 模块使用指南
   - 运维面板部署说明
   - 回测引擎 API 文档

---

## 五、风险与注意事项

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 窗口 A 契约文件变更 | 类型不匹配 | 已在 `ai/schema.py` 中明确字段定义，变更时同步讨论 |
| 模型 API 限流/不稳定 | 分析延迟或失败 | 实现降级：缓存命中时延长有效期，失败时返回历史分析 |
| 输入数据质量问题 | AI 输出置信度虚高 | 强制要求 `data_completeness` 字段，低完整度时降低 confidence |
| Secrets 泄露 | 安全风险 | API Key 只走环境变量，绝不写入文件或日志 |

---

## 六、代码统计

```
ai/           4 文件  ~280 行有效代码
backtest/     2 文件  ~280 行有效代码
web_admin/    1 文件  ~150 行有效代码
tests/        3 文件  ~200 行测试代码
总计         10 文件  ~900 行代码
```

---

## 七、同步记录

- 同步日志：`ops/sync_log.md` 已更新两条记录（22:35, 22:50）
- 契约版本：等待窗口 A 确认 `CONTRACT_VERSION`

---

**总结：** 今日按计划完成 AI + 运维模块的核心骨架，实现单模型分析、三模型裁决、回测引擎、运维面板、单元测试。等待窗口 A 数据闭环后即可联调端到端流程。
