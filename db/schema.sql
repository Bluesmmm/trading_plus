-- 基金交易系统数据库 Schema
-- CONTRACT_VERSION: 20260128.1
-- 此文件与 core/types.py 保持一致

-- 启用 UUID 扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =============================================================================
-- 1. 用户表
-- =============================================================================
CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,  -- Telegram User ID
    username VARCHAR(255),
    risk_level VARCHAR(50) DEFAULT 'moderate',  -- conservative / moderate / aggressive
    preferences JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_users_username ON users(username);

-- =============================================================================
-- 2. 基金主表
-- =============================================================================
CREATE TABLE IF NOT EXISTS fund_master (
    fund_code VARCHAR(20) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    fund_type VARCHAR(20) NOT NULL DEFAULT 'mutual',  -- mutual / etf / index / lof
    currency VARCHAR(10) DEFAULT 'CNY',
    data_source_priority JSONB DEFAULT '["eastmoney", "akshare"]',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_fund_master_type ON fund_master(fund_type);

-- =============================================================================
-- 3. 净值时间序列
-- =============================================================================
CREATE TABLE IF NOT EXISTS fund_nav_timeseries (
    id BIGSERIAL PRIMARY KEY,
    fund_code VARCHAR(20) NOT NULL REFERENCES fund_master(fund_code) ON DELETE CASCADE,
    nav_date DATE NOT NULL,
    nav DECIMAL(12, 6) NOT NULL CHECK (nav > 0),
    acc_nav DECIMAL(12, 6),  -- 累计净值
    daily_pct DECIMAL(10, 4),  -- 日涨跌幅（百分比）
    data_source VARCHAR(50) NOT NULL,
    last_updated_at TIMESTAMPTZ NOT NULL,
    quality_flags JSONB DEFAULT '[]',  -- ["ok"] / ["outlier"] / ["missing_fields"]
    ingested_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(fund_code, nav_date)
);

CREATE INDEX idx_nav_fund_date ON fund_nav_timeseries(fund_code, nav_date DESC);
CREATE INDEX idx_nav_date ON fund_nav_timeseries(nav_date DESC);

-- =============================================================================
-- 4. 模拟交易事件表（事实源）
-- =============================================================================
CREATE TABLE IF NOT EXISTS simulation_trades (
    trade_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    fund_code VARCHAR(20) NOT NULL REFERENCES fund_master(fund_code) ON DELETE CASCADE,
    trade_type VARCHAR(20) NOT NULL CHECK (trade_type IN ('buy', 'sell', 'sip')),
    shares DECIMAL(14, 4),  -- 卖出时必填
    amount DECIMAL(14, 2),  -- 买入时必填
    nav_price DECIMAL(12, 6) NOT NULL CHECK (nav_price > 0),
    trade_date DATE NOT NULL,
    settle_date DATE,  -- T+1 结算日期
    trade_status VARCHAR(20) NOT NULL DEFAULT 'created' CHECK (trade_status IN ('created', 'confirmed', 'settled', 'cancelled', 'failed')),
    idempotency_key VARCHAR(255) NOT NULL UNIQUE,
    raw_source JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    CHECK (
        (trade_type = 'buy' AND amount IS NOT NULL AND shares IS NULL) OR
        (trade_type = 'sell' AND shares IS NOT NULL AND amount IS NULL) OR
        (trade_type = 'sip' AND amount IS NOT NULL)
    )
);

CREATE INDEX idx_trades_user_fund ON simulation_trades(user_id, fund_code, trade_date DESC);
CREATE INDEX idx_trades_status ON simulation_trades(trade_status);
CREATE INDEX idx_trades_settle_date ON simulation_trades(settle_date) WHERE settle_date IS NOT NULL;

-- =============================================================================
-- 5. 持仓快照（物化视图或定时刷新）
-- =============================================================================
CREATE TABLE IF NOT EXISTS positions_snapshot (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    fund_code VARCHAR(20) NOT NULL REFERENCES fund_master(fund_code) ON DELETE CASCADE,
    shares DECIMAL(14, 4) NOT NULL CHECK (shares >= 0),
    avg_cost DECIMAL(12, 6) NOT NULL CHECK (avg_cost > 0),
    as_of_date DATE NOT NULL,
    unrealized_pnl DECIMAL(14, 2),
    last_nav DECIMAL(12, 6),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, fund_code, as_of_date)
);

CREATE INDEX idx_positions_user ON positions_snapshot(user_id, as_of_date DESC);
CREATE INDEX idx_positions_date ON positions_snapshot(as_of_date DESC);

-- =============================================================================
-- 6. 预警规则
-- =============================================================================
CREATE TABLE IF NOT EXISTS alert_rules (
    rule_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    fund_code VARCHAR(20),  -- NULL 表示监控所有基金
    rule_type VARCHAR(20) NOT NULL CHECK (rule_type IN ('threshold', 'drawdown', 'volatility', 'new_high', 'new_low')),
    params JSONB NOT NULL,  -- AlertRuleParams
    enabled BOOLEAN DEFAULT TRUE,
    cooldown_seconds INTEGER NOT NULL DEFAULT 3600 CHECK (cooldown_seconds > 0),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_alert_rules_user ON alert_rules(user_id, enabled);
CREATE INDEX idx_alert_rules_fund ON alert_rules(fund_code) WHERE fund_code IS NOT NULL;

-- =============================================================================
-- 7. 预警事件（去重键保证唯一性）
-- =============================================================================
CREATE TABLE IF NOT EXISTS alert_events (
    event_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    rule_id UUID NOT NULL REFERENCES alert_rules(rule_id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    fund_code VARCHAR(20) NOT NULL REFERENCES fund_master(fund_code) ON DELETE CASCADE,
    rule_type VARCHAR(20) NOT NULL,
    triggered_at TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL,  -- 预警具体数值
    dedup_key VARCHAR(255) NOT NULL UNIQUE,  -- user_id:fund_code:rule_type:window_bucket
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'sent', 'suppressed', 'failed')),
    sent_at TIMESTAMPTZ,
    error TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_alert_events_user ON alert_events(user_id, triggered_at DESC);
CREATE INDEX idx_alert_events_dedup ON alert_events(dedup_key);
CREATE INDEX idx_alert_events_status ON alert_events(status);

-- =============================================================================
-- 8. 任务调度表（幂等与重试）
-- =============================================================================
CREATE TABLE IF NOT EXISTS jobs (
    job_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_type VARCHAR(50) NOT NULL CHECK (job_type IN ('nav_sync', 'settle', 'alert_check', 'ai_analyze')),
    scheduled_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
    attempt INTEGER NOT NULL DEFAULT 0 CHECK (attempt >= 0),
    max_attempts INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts > 0),
    idempotency_key VARCHAR(255) NOT NULL UNIQUE,  -- job_type:params_hash:scheduled_at
    payload JSONB,
    error TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_jobs_type_status ON jobs(job_type, status);
CREATE INDEX idx_jobs_scheduled ON jobs(scheduled_at) WHERE status IN ('pending', 'running');
CREATE INDEX idx_jobs_idempotency ON jobs(idempotency_key);

-- =============================================================================
-- 9. AI 分析结果（可追溯）
-- =============================================================================
CREATE TABLE IF NOT EXISTS ai_analyses (
    analysis_id UUID PRIMARY KEY,
    user_id BIGINT REFERENCES users(user_id) ON DELETE SET NULL,
    fund_code VARCHAR(20) NOT NULL REFERENCES fund_master(fund_code) ON DELETE CASCADE,
    as_of_date DATE NOT NULL,
    input_hash VARCHAR(64) NOT NULL,  -- SHA-256 of input JSON
    providers_json JSONB,  -- 各模型原始输出
    verdict_json JSONB NOT NULL,  -- 裁决后的最终输出（AIAnalysisOutput）
    prompt_version VARCHAR(20) DEFAULT 'v1.0',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_ai_analyses_fund ON ai_analyses(fund_code, as_of_date DESC);
CREATE INDEX idx_ai_analyses_input_hash ON ai_analyses(input_hash);

-- =============================================================================
-- 触发器：自动更新 updated_at
-- =============================================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_fund_master_updated_at BEFORE UPDATE ON fund_master
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_trades_updated_at BEFORE UPDATE ON simulation_trades
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_alert_rules_updated_at BEFORE UPDATE ON alert_rules
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- 注释
-- =============================================================================
COMMENT ON TABLE simulation_trades IS '交易事件事实表，持仓从此表重建';
COMMENT ON TABLE positions_snapshot IS '持仓物化快照，可从 simulation_trades 重建';
COMMENT ON TABLE fund_nav_timeseries IS '净值时间序列，必须包含 data_source 和 quality_flags';
COMMENT ON TABLE alert_events IS '预警事件，dedup_key 保证去重';
COMMENT ON TABLE jobs IS '任务调度表，idempotency_key 保证幂等';
