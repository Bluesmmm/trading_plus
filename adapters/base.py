"""
数据源适配器基类

所有数据源必须实现此接口，确保返回格式一致：
{data, last_updated_at, quality_flags}
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Generic, Optional, TypeVar

from core.types import DataSource, QualityFlag

T = TypeVar("T")


class AdapterResult(dict, Generic[T]):
    """适配器返回格式（强约束）"""
    data: T
    data_source: DataSource
    last_updated_at: datetime
    quality_flags: list[QualityFlag]

    def __init__(
        self,
        data: T,
        data_source: DataSource,
        last_updated_at: datetime,
        quality_flags: Optional[list[QualityFlag]] = None,
    ):
        super().__init__()
        self.data = data
        self.data_source = data_source
        self.last_updated_at = last_updated_at
        self.quality_flags = quality_flags or [QualityFlag.OK]


class AdapterError(Exception):
    """适配器错误（带降级提示）"""
    def __init__(self, message: str, can_fallback: bool = True, fallback_source: Optional[DataSource] = None):
        self.message = message
        self.can_fallback = can_fallback
        self.fallback_source = fallback_source
        super().__init__(message)


class DataAdapter(ABC, Generic[T]):
    """
    数据源适配器抽象基类

    约束：
    1. 所有 fetch* 方法必须返回 AdapterResult
    2. 必须包含 health_check 方法
    3. 错误必须抛出 AdapterError
    """

    def __init__(self, source: DataSource, timeout: int = 30):
        self.source = source
        self.timeout = timeout

    @abstractmethod
    async def fetch_fund_info(self, fund_code: str) -> AdapterResult[dict]:
        """
        获取基金基础信息

        返回数据必须包含：
        - fund_code: str
        - name: str
        - fund_type: str
        - currency: str (可选，默认 CNY)
        """
        raise NotImplementedError

    @abstractmethod
    async def fetch_nav(self, fund_code: str, nav_date: Optional[str] = None) -> AdapterResult[dict]:
        """
        获取净值数据

        返回数据必须包含：
        - fund_code: str
        - nav_date: date (YYYY-MM-DD)
        - nav: float
        - acc_nav: float (可选)
        - daily_pct: float (可选)
        """
        raise NotImplementedError

    @abstractmethod
    async def fetch_nav_series(
        self, fund_code: str, start_date: str, end_date: str
    ) -> AdapterResult[list[dict]]:
        """
        获取净值序列

        返回数据是 list，每项同 fetch_nav
        """
        raise NotImplementedError

    @abstractmethod
    async def health_check(self) -> dict[str, bool | str]:
        """
        健康检查

        返回：
        {
            "reachable": bool,
            "latency_ms": int,
            "error": str | None
        }
        """
        raise NotImplementedError

    def _detect_outlier(self, nav: float, prev_nav: Optional[float]) -> bool:
        """异常值检测（日涨跌幅 > 20%）"""
        if prev_nav is None or prev_nav == 0:
            return False
        pct_change = abs((nav - prev_nav) / prev_nav) * 100
        return pct_change > 20

    def _is_stale(self, last_updated_at: datetime, max_age_hours: int = 48) -> bool:
        """检测数据是否过期"""
        return (datetime.utcnow() - last_updated_at.replace(tzinfo=None)).totalseconds() > max_age_hours * 3600
