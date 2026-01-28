"""
核心类型契约（CONTRACT_VERSION=20260128.1）

本模块定义系统所有公共数据结构，是多模块协作的契约基础。
任何修改必须同步更新 CONTRACT_VERSION 并在 PLAN.md 记录。

所有类型均使用 Pydantic v2 实现，确保运行时验证与 JSON 序列化一致性。
"""

from datetime import date, datetime
from enum import Enum
from typing import Generic, Literal, Optional, TypeVar
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

T = TypeVar("T")


# =============================================================================
# 基础枚举
# =============================================================================

class FundType(str, Enum):
    """基金类型"""
    MUTUAL = "mutual"  # 场外公募基金
    ETF = "etf"  # 场内 ETF
    INDEX = "index"  # 指数
    LOF = "lof"  # LOF


class TradeType(str, Enum):
    """交易类型"""
    BUY = "buy"
    SELL = "sell"
    SIP = "sip"  # 定投


class TradeStatus(str, Enum):
    """交易状态（状态机）"""
    CREATED = "created"
    CONFIRMED = "confirmed"
    SETTLED = "settled"
    CANCELLED = "cancelled"
    FAILED = "failed"


class AlertRuleType(str, Enum):
    """预警规则类型"""
    THRESHOLD = "threshold"  # 阈值（净值/涨跌幅）
    DRAWDOWN = "drawdown"  # 回撤
    VOLATILITY = "volatility"  # 波动率
    NEW_HIGH = "new_high"  # 创新高
    NEW_LOW = "new_low"  # 创新低


class AlertStatus(str, Enum):
    """预警状态"""
    PENDING = "pending"
    SENT = "sent"
    SUPPRESSED = "suppressed"  # 被冷却窗口抑制
    FAILED = "failed"


class JobType(str, Enum):
    """任务类型"""
    NAV_SYNC = "nav_sync"  # 净值同步
    SETTLE = "settle"  # 结算
    ALERT_CHECK = "alert_check"  # 预警检查
    AI_ANALYZE = "ai_analyze"  # AI 分析


class JobStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DataSource(str, Enum):
    """数据源标识"""
    EASTMONEY = "eastmoney"
    AKSHARE = "akshare"
    TUSHARE = "tushare"
    MANUAL = "manual"


class QualityFlag(str, Enum):
    """数据质量标记"""
    OK = "ok"
    MISSING_FIELDS = "missing_fields"
    OUTLIER = "outlier"
    DELAYED = "delayed"
    STALE = "stale"  # 过期数据


# =============================================================================
# 基金与净值数据
# =============================================================================

class Fund(BaseModel):
    """基金基础信息"""
    fund_code: str = Field(..., description="基金代码（6位数字）")
    name: str = Field(..., description="基金名称")
    fund_type: FundType = Field(default=FundType.MUTUAL, description="基金类型")
    currency: str = Field(default="CNY", description="币种")
    data_source_priority: list[DataSource] = Field(
        default=[DataSource.EASTMONEY, DataSource.AKSHARE],
        description="数据源优先级"
    )


class NAV(BaseModel):
    """净值数据（带来源与质量标记）"""
    fund_code: str = Field(..., description="基金代码")
    nav_date: date = Field(..., description="净值日期")
    nav: float = Field(..., description="单位净值", gt=0)
    acc_nav: Optional[float] = Field(None, description="累计净值", gt=0)
    daily_pct: Optional[float] = Field(None, description="日涨跌幅（百分比）")
    data_source: DataSource = Field(..., description="数据源")
    last_updated_at: datetime = Field(..., description="数据源更新时间")
    quality_flags: list[QualityFlag] = Field(default_factory=list, description="质量标记")
    ingested_at: datetime = Field(default_factory=datetime.utcnow, description="入库时间")

    @field_validator("daily_pct")
    @classmethod
    def validate_daily_pct(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (-100 <= v <= 100):
            raise ValueError("daily_pct 必须在 -100 到 100 之间")
        return v


# =============================================================================
# 交易事件与持仓
# =============================================================================

class Trade(BaseModel):
    """交易事件（事实表）"""
    trade_id: UUID = Field(..., description="交易 ID")
    user_id: int = Field(..., description="Telegram User ID")
    fund_code: str = Field(..., description="基金代码")
    trade_type: TradeType = Field(..., description="交易类型")
    shares: Optional[float] = Field(None, description="交易份额（卖出时必填）", gt=0)
    amount: Optional[float] = Field(None, description="交易金额（买入时必填）", gt=0)
    nav_price: float = Field(..., description="成交净值", gt=0)
    trade_date: date = Field(..., description="交易日期")
    settle_date: Optional[date] = Field(None, description="结算日期（T+1）")
    trade_status: TradeStatus = Field(default=TradeStatus.CREATED, description="交易状态")
    idempotency_key: str = Field(..., description="幂等键（保证唯一性）")
    raw_source: Optional[dict] = Field(None, description="原始数据源（追溯）")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="更新时间")

    @field_validator("idempotency_key")
    @classmethod
    def validate_idempotency_key(cls, v: str) -> str:
        """幂等键格式：user_id:fund_code:type:date:amount:nav:client_msg_id"""
        parts = v.split(":")
        if len(parts) < 6:
            raise ValueError("idempotency_key 格式错误")
        return v


class Position(BaseModel):
    """持仓（可从交易事件重建）"""
    user_id: int = Field(..., description="用户 ID")
    fund_code: str = Field(..., description="基金代码")
    shares: float = Field(..., description="持有份额", ge=0)
    avg_cost: float = Field(..., description="平均成本", gt=0)
    as_of_date: date = Field(..., description="截止日期")
    unrealized_pnl: Optional[float] = Field(None, description="未实现盈亏")
    last_nav: Optional[float] = Field(None, description="最新净值")


# =============================================================================
# 预警规则与事件
# =============================================================================

class AlertRuleParams(BaseModel):
    """预警规则参数（JSON）"""
    threshold_value: Optional[float] = Field(None, description="阈值")
    threshold_pct: Optional[float] = Field(None, description="百分比阈值")
    window_days: int = Field(default=1, description="窗口期（天）", gt=0)
    min_trigger_pct: Optional[float] = Field(None, description="最小触发幅度")


class AlertRule(BaseModel):
    """预警规则"""
    rule_id: UUID = Field(..., description="规则 ID")
    user_id: int = Field(..., description="用户 ID")
    fund_code: Optional[str] = Field(None, description="基金代码（空则监控所有）")
    rule_type: AlertRuleType = Field(..., description="规则类型")
    params: AlertRuleParams = Field(..., description="规则参数")
    enabled: bool = Field(default=True, description="是否启用")
    cooldown_seconds: int = Field(default=3600, description="冷却窗口（秒）", gt=0)
    created_at: datetime = Field(default_factory=datetime.utcnow, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="更新时间")


class AlertEvent(BaseModel):
    """预警事件（去重键保证唯一性）"""
    event_id: UUID = Field(..., description="事件 ID")
    rule_id: UUID = Field(..., description="触发规则 ID")
    user_id: int = Field(..., description="用户 ID")
    fund_code: str = Field(..., description="基金代码")
    rule_type: AlertRuleType = Field(..., description="规则类型")
    triggered_at: datetime = Field(..., description="触发时间")
    payload: dict = Field(..., description="预警载荷（具体数值）")
    dedup_key: str = Field(..., description="去重键：user_id:fund_code:rule_type:window_bucket")
    status: AlertStatus = Field(default=AlertStatus.PENDING, description="状态")
    sent_at: Optional[datetime] = Field(None, description="发送时间")
    error: Optional[str] = Field(None, description="错误信息")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="创建时间")


# =============================================================================
# 任务调度
# =============================================================================

class Job(BaseModel):
    """任务记录（幂等与重试）"""
    job_id: UUID = Field(..., description="任务 ID")
    job_type: JobType = Field(..., description="任务类型")
    scheduled_at: datetime = Field(..., description="计划执行时间")
    started_at: Optional[datetime] = Field(None, description="实际开始时间")
    finished_at: Optional[datetime] = Field(None, description="完成时间")
    status: JobStatus = Field(default=JobStatus.PENDING, description="状态")
    attempt: int = Field(default=0, description="尝试次数", ge=0)
    max_attempts: int = Field(default=3, description="最大重试次数", gt=0)
    idempotency_key: str = Field(..., description="幂等键：job_type:params_hash:scheduled_at")
    payload: Optional[dict] = Field(None, description="任务载荷")
    error: Optional[str] = Field(None, description="错误信息")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="创建时间")


# =============================================================================
# AI 分析（可追溯）
# =============================================================================

class AIAnalysisInput(BaseModel):
    """AI 分析输入（结构化事实）"""
    fund_code: str = Field(..., description="基金代码")
    as_of_date: date = Field(..., description="截止日期")
    nav_series: list[NAV] = Field(..., description="净值序列")
    returns: dict[str, float] = Field(..., description="收益：1W/1M/3M/1Y")
    max_drawdown: float = Field(..., description="最大回撤（百分比）")
    volatility: float = Field(..., description="年化波动率")
    sharpe_ratio: Optional[float] = Field(None, description="夏普比率")
    benchmark_returns: Optional[dict[str, float]] = Field(None, description="基准收益")
    quality_flags: list[QualityFlag] = Field(default_factory=list, description="数据质量标记")


class AIAnalysisAction(BaseModel):
    """AI 输出的操作建议（受限）"""
    action_type: Literal["watch", "compare", "hold"] = Field(..., description="操作类型")
    reason: str = Field(..., description="理由")
    confidence: Optional[float] = Field(None, description="置信度", ge=0, le=1)


class AIAnalysisOutput(BaseModel):
    """AI 分析输出（强 Schema）"""
    analysis_id: UUID = Field(..., description="分析 ID")
    fund_code: str = Field(..., description="基金代码")
    as_of_date: date = Field(..., description="分析日期")
    facts_used: list[str] = Field(..., description="使用的指标列表")
    unknowns: list[str] = Field(default_factory=list, description="缺失/未知字段")
    risk_notes: list[str] = Field(..., description="风险提示")
    actions: list[AIAnalysisAction] = Field(..., description="建议操作（仅弱指令）")
    provider: str = Field(..., description="模型提供商")
    model_version: str = Field(..., description="模型版本")
    input_hash: str = Field(..., description="输入数据的 hash（追溯）")
    prompt_version: str = Field(default="v1.0", description="Prompt 版本")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="创建时间")


# =============================================================================
# 通用响应格式
# =============================================================================

class ApiResponse(BaseModel, Generic[T]):
    """统一 API 响应格式"""
    success: bool = Field(..., description="是否成功")
    data: Optional[T] = Field(None, description="返回数据")
    error: Optional[str] = Field(None, description="错误信息")
    meta: Optional[dict] = Field(None, description="元数据（分页、总数等）")


class DataWithSource(BaseModel, Generic[T]):
    """带数据源信息的响应"""
    data: T = Field(..., description="数据")
    data_source: DataSource = Field(..., description="数据源")
    last_updated_at: datetime = Field(..., description="更新时间")
    quality_flags: list[QualityFlag] = Field(default_factory=list, description="质量标记")
