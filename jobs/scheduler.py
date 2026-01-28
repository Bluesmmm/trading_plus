"""
任务调度器

功能：定时任务、幂等执行、重试、状态追踪
"""

import os
from datetime import date, datetime, timedelta
from hashlib import sha256
from typing import Optional
from uuid import UUID, uuid4

import asyncpg
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from adapters import EastMoneyAdapter
from core.alerts import AlertEngine
from core.events import TradeService
from core.types import Job, JobStatus, JobType


class JobScheduler:
    """
    任务调度器

    支持的任务类型：
    - nav_sync: 净值同步
    - settle: 交易结算
    - alert_check: 预警检查
    """

    def __init__(self):
        self.db_pool: Optional[asyncpg.Pool] = None
        self.scheduler = AsyncIOScheduler()
        self.adapter = EastMoneyAdapter()
        self.trade_svc: Optional[TradeService] = None
        self.alert_engine: Optional[AlertEngine] = None
        self.monitored_funds: list[str] = []

    async def init_db(self):
        """初始化数据库连接"""
        db_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost/trading_plus")
        self.db_pool = await asyncpg.create_pool(db_url, min_size=2, max_size=10)

        self.trade_svc = TradeService(self.db_pool)
        self.alert_engine = AlertEngine(self.db_pool)

    async def close(self):
        """关闭连接"""
        self.scheduler.shutdown()
        if self.db_pool:
            await self.db_pool.close()
        await self.adapter.close()

    def _generate_idempotency_key(self, job_type: JobType, params: dict, scheduled_at: datetime) -> str:
        """生成幂等键"""
        params_str = str(sorted(params.items()))
        key_string = f"{job_type.value}:{params_str}:{scheduled_at.isoformat()}"
        return sha256(key_string.encode()).hexdigest()

    async def _create_job(
        self,
        job_type: JobType,
        scheduled_at: datetime,
        payload: Optional[dict] = None,
    ) -> Job:
        """创建任务记录（带幂等检查）"""
        idempotency_key = self._generate_idempotency_key(job_type, payload or {}, scheduled_at)

        # 检查是否已存在
        existing = await self.db_pool.fetchrow(  # type: ignore[union-attr]
            "SELECT * FROM jobs WHERE idempotency_key = $1",
            idempotency_key,
        )

        if existing:
            return Job(**dict(existing))

        # 创建新任务
        job = Job(
            job_id=uuid4(),
            job_type=job_type,
            scheduled_at=scheduled_at,
            status=JobStatus.PENDING,
            idempotency_key=idempotency_key,
            payload=payload,
        )

        await self.db_pool.execute(  # type: ignore[union-attr]
            """
            INSERT INTO jobs (
                job_id, job_type, scheduled_at, status, idempotency_key, payload
            ) VALUES ($1, $2, $3, $4, $5, $6)
            """,
            job.job_id,
            job.job_type.value,
            job.scheduled_at,
            job.status.value,
            job.idempotency_key,
            job.payload,
        )

        return job

    async def _update_job_status(self, job_id: UUID, status: JobStatus, error: Optional[str] = None):
        """更新任务状态"""
        fields = ["status = $2"]
        values = [status.value]
        param_idx = 3

        if status == JobStatus.RUNNING:
            fields.append(f"started_at = NOW()")
            fields.append(f"attempt = attempt + 1")
        elif status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            fields.append(f"finished_at = NOW()")

        if error:
            fields.append(f"error = ${param_idx}")
            values.append(error)
            param_idx += 1

        values.insert(0, job_id)
        values.append(job_id)

        query = f"UPDATE jobs SET {', '.join(fields)} WHERE job_id = ${param_idx}"
        await self.db_pool.execute(query, *values)  # type: ignore[ignore-call-arg]

    # ========================================================================
    # 任务实现
    # ========================================================================

    async def _run_nav_sync(self, job: Job):
        """
        净值同步任务

        拉取监控基金的净值数据并入库
        """
        fund_codes = job.payload.get("fund_codes", self.monitored_funds) if job.payload else self.monitored_funds

        if not fund_codes:
            raise ValueError("没有配置监控基金列表")

        sync_date = date.today()
        count = 0

        for fund_code in fund_codes:
            try:
                # 获取最新净值
                result = await self.adapter.fetch_nav(fund_code)
                nav_data = result.data

                # 入库
                await self.db_pool.execute(  # type: ignore[union-attr]
                    """
                    INSERT INTO fund_nav_timeseries (
                        fund_code, nav_date, nav, acc_nav, daily_pct,
                        data_source, last_updated_at, quality_flags
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (fund_code, nav_date) DO UPDATE SET
                        nav = EXCLUDED.nav,
                        acc_nav = EXCLUDED.acc_nav,
                        daily_pct = EXCLUDED.daily_pct,
                        data_source = EXCLUDED.data_source,
                        last_updated_at = EXCLUDED.last_updated_at,
                        quality_flags = EXCLUDED.quality_flags
                    """,
                    fund_code,
                    nav_data["nav_date"],
                    nav_data["nav"],
                    nav_data.get("acc_nav"),
                    nav_data.get("daily_pct"),
                    result.data_source.value,
                    result.last_updated_at,
                    [q.value for q in result.quality_flags],
                )

                count += 1

            except Exception as e:
                print(f"同步 {fund_code} 失败: {e}")

        print(f"净值同步完成: {count}/{len(fund_codes)} 只基金")

    async def _run_settle(self, job: Job):
        """
        结算任务

        结算所有已确认但未结算的交易
        """
        # 获取待结算交易
        rows = await self.db_pool.fetch(  # type: ignore[union-attr]
            """
            SELECT trade_id FROM simulation_trades
            WHERE trade_status = 'confirmed'
              OR (trade_status = 'created' AND trade_date < CURRENT_DATE)
            ORDER BY trade_date ASC
            """
        )

        count = 0
        for row in rows:
            try:
                await self.trade_svc.settle_trade(row["trade_id"])  # type: ignore[union-attr]
                count += 1
            except Exception as e:
                print(f"结算交易 {row['trade_id']} 失败: {e}")

        print(f"结算完成: {count} 笔交易")

    async def _run_alert_check(self, job: Job):
        """
        预警检查任务

        检查所有启用的预警规则是否触发
        """
        # 获取所有启用的规则
        rows = await self.db_pool.fetch(  # type: ignore[union-attr]
            """
            SELECT r.* FROM alert_rules r
            WHERE r.enabled = true
            ORDER BY r.created_at ASC
            """
        )

        triggered_count = 0

        for row in rows:
            # 解析规则
            rule_data = dict(row)
            params = rule_data.pop("params")

            from core.types import AlertRule
            rule = AlertRule(**rule_data, params=params)

            # 获取净值数据
            fund_code = rule.fund_code or self.monitored_funds[0] if self.monitored_funds else None
            if not fund_code:
                continue

            try:
                # 获取窗口期净值序列
                window_days = rule.params.window_days
                end_date = date.today()
                start_date = end_date - timedelta(days=window_days * 2)

                result = await self.adapter.fetch_nav_series(fund_code, start_date.isoformat(), end_date.isoformat())
                nav_series = [nav["nav"] for nav in result.data[-window_days:]]
                current_nav = nav_series[-1] if nav_series else 0

                # 检查规则
                event = await self.alert_engine.check_rule(  # type: ignore[union-attr]
                    rule=rule,
                    current_nav=current_nav,
                    nav_series=nav_series,
                    triggered_at=datetime.utcnow(),
                )

                if event and event.status.value != "suppressed":
                    triggered_count += 1

            except Exception as e:
                print(f"检查规则 {rule.rule_id} 失败: {e}")

        print(f"预警检查完成: {triggered_count} 个新触发")

    # ========================================================================
    # 任务执行包装器
    # ========================================================================

    async def _execute_job(self, job_id: UUID):
        """执行任务（带重试）"""
        # 获取任务
        row = await self.db_pool.fetchrow("SELECT * FROM jobs WHERE job_id = $1", job_id)  # type: ignore[union-attr]
        if not row:
            return

        job = Job(**dict(row))

        # 更新为运行中
        await self._update_job_status(job_id, JobStatus.RUNNING)

        try:
            # 根据类型执行
            if job.job_type == JobType.NAV_SYNC:
                await self._run_nav_sync(job)
            elif job.job_type == JobType.SETTLE:
                await self._run_settle(job)
            elif job.job_type == JobType.ALERT_CHECK:
                await self._run_alert_check(job)
            else:
                raise ValueError(f"未知任务类型: {job.job_type}")

            # 标记完成
            await self._update_job_status(job_id, JobStatus.COMPLETED)

        except Exception as e:
            # 检查是否需要重试
            if job.attempt < job.max_attempts:
                await self._update_job_status(job_id, JobStatus.PENDING, error=str(e))
            else:
                await self._update_job_status(job_id, JobStatus.FAILED, error=str(e))
            print(f"任务 {job_id} 失败: {e}")

    # ========================================================================
    # 调度器配置
    # ========================================================================

    def add_monitored_fund(self, fund_code: str):
        """添加监控基金"""
        if fund_code not in self.monitored_funds:
            self.monitored_funds.append(fund_code)

    async def schedule_nav_sync(self, hour: int = 16, minute: int = 30):
        """调度净值同步任务（每个交易日收盘后）"""
        scheduled_at = datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
        job = await self._create_job(JobType.NAV_SYNC, scheduled_at, {"fund_codes": self.monitored_funds})

        self.scheduler.add_job(
            self._execute_job,
            "cron",
            hour=hour,
            minute=minute,
            args=[job.job_id],
            id=f"nav_sync_{job.job_id}",
        )

        print(f"已调度净值同步任务: 每天 {hour:02d}:{minute:02d}")

    async def schedule_settle(self, hour: int = 17, minute: int = 0):
        """调度结算任务（每个交易日收盘后）"""
        scheduled_at = datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
        job = await self._create_job(JobType.SETTLE, scheduled_at)

        self.scheduler.add_job(
            self._execute_job,
            "cron",
            hour=hour,
            minute=minute,
            args=[job.job_id],
            id=f"settle_{job.job_id}",
        )

        print(f"已调度结算任务: 每天 {hour:02d}:{minute:02d}")

    async def schedule_alert_check(self, hour: int = 18, minute: int = 0):
        """调度预警检查任务（每个交易日收盘后）"""
        scheduled_at = datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
        job = await self._create_job(JobType.ALERT_CHECK, scheduled_at)

        self.scheduler.add_job(
            self._execute_job,
            "cron",
            hour=hour,
            minute=minute,
            args=[job.job_id],
            id=f"alert_check_{job.job_id}",
        )

        print(f"已调度预警检查任务: 每天 {hour:02d}:{minute:02d}")

    def start(self):
        """启动调度器"""
        self.scheduler.start()
        print("调度器已启动")


def main():
    """主入口"""
    import asyncio

    scheduler = JobScheduler()

    async def run():  # type: ignore[no-untyped-def]
        await scheduler.init_db()

        # 添加监控基金
        scheduler.add_monitored_fund("000001")  # 示例：华夏成长
        scheduler.add_monitored_fund("110022")  # 示例：易方达消费行业

        # 调度任务
        await scheduler.schedule_nav_sync(hour=16, minute=30)
        await scheduler.schedule_settle(hour=17, minute=0)
        await scheduler.schedule_alert_check(hour=18, minute=0)

        scheduler.start()

        # 保持运行
        try:
            while True:
                await asyncio.sleep(3600)
        except KeyboardInterrupt:
            print("停止调度器...")
        finally:
            await scheduler.close()

    asyncio.run(run())


if __name__ == "__main__":
    main()
