"""
东方财富数据源适配器

使用 AkShare 封装，提供基金净值、基础信息等数据。
数据源：https://fund.eastmoney.com/
"""

import asyncio
from datetime import date, datetime
from typing import Optional

import akshare as ak
import httpx

from adapters.base import DataAdapter, AdapterError, AdapterResult
from core.types import DataSource, FundType, QualityFlag


class EastMoneyAdapter(DataAdapter):
    """
    东方财富数据适配器

    数据特性：
    - 场外基金净值：交易日 16:00-23:00 更新
    - ETF 日线：收盘后更新
    """

    def __init__(self, timeout: int = 30):
        super().__init__(source=DataSource.EASTMONEY, timeout=timeout)
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()

    async def fetch_fund_info(self, fund_code: str) -> AdapterResult[dict]:
        """
        获取基金基础信息

        使用 AkShare: fund_em_open_fund_info()
        """
        try:
            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(
                None,
                lambda: ak.fund_em_open_fund_info(fund=fund_code, indicator="单位净值走势")
            )

            if info.empty:
                raise AdapterError(f"基金 {fund_code} 信息未找到")

            # 解析返回数据
            row = info.iloc[0] if len(info) > 0 else None
            if row is None:
                raise AdapterError(f"基金 {fund_code} 数据为空")

            data = {
                "fund_code": fund_code,
                "name": row.get("基金简称", f"基金{fund_code}"),
                "fund_type": self._map_fund_type(row.get("基金类型", "开放式")),
                "currency": "CNY",
            }

            return AdapterResult(
                data=data,
                data_source=self.source,
                last_updated_at=datetime.utcnow(),
                quality_flags=[QualityFlag.OK],
            )

        except Exception as e:
            if isinstance(e, AdapterError):
                raise
            raise AdapterError(
                f"获取基金信息失败: {e}",
                can_fallback=True,
                fallback_source=DataSource.AKSHARE,
            )

    async def fetch_nav(self, fund_code: str, nav_date: Optional[str] = None) -> AdapterResult[dict]:
        """
        获取单日净值数据

        使用 AkShare: fund_em_open_fund_info()
        """
        try:
            loop = asyncio.get_event_loop()
            df = await loop.run_in_executor(
                None,
                lambda: ak.fund_em_open_fund_info(fund=fund_code, indicator="单位净值走势")
            )

            if df.empty:
                raise AdapterError(f"基金 {fund_code} 净值数据未找到")

            # 转换日期列
            df["净值日期"] = pd.to_datetime(df["净值日期"])

            # 如果指定日期，筛选该日期
            if nav_date:
                target_date = pd.to_datetime(nav_date)
                df = df[df["净值日期"] == target_date]

            # 取最新一行
            if df.empty:
                raise AdapterError(f"基金 {fund_code} 在 {nav_date} 无净值数据")

            row = df.iloc[-1]

            # 质量检查
            quality_flags = [QualityFlag.OK]
            nav_val = float(row.get("单位净值", 0))
            if nav_val <= 0:
                quality_flags.append(QualityFlag.MISSING_FIELDS)

            data = {
                "fund_code": fund_code,
                "nav_date": row["净值日期"].date(),
                "nav": nav_val,
                "acc_nav": float(row.get("累计净值", nav_val)),
                "daily_pct": float(row.get("日增长率", 0).rstrip("%")) if row.get("日增长率") else None,
            }

            return AdapterResult(
                data=data,
                data_source=self.source,
                last_updated_at=datetime.utcnow(),
                quality_flags=quality_flags,
            )

        except Exception as e:
            if isinstance(e, AdapterError):
                raise
            raise AdapterError(
                f"获取净值失败: {e}",
                can_fallback=True,
                fallback_source=DataSource.AKSHARE,
            )

    async def fetch_nav_series(
        self, fund_code: str, start_date: str, end_date: str
    ) -> AdapterResult[list[dict]]:
        """
        获取净值序列

        使用 AkShare: fund_em_open_fund_info()
        """
        try:
            loop = asyncio.get_event_loop()
            df = await loop.run_in_executor(
                None,
                lambda: ak.fund_em_open_fund_info(fund=fund_code, indicator="单位净值走势")
            )

            if df.empty:
                raise AdapterError(f"基金 {fund_code} 净值数据未找到")

            # 转换并筛选日期
            df["净值日期"] = pd.to_datetime(df["净值日期"])
            start_dt = pd.to_datetime(start_date)
            end_dt = pd.to_datetime(end_date)
            df = df[(df["净值日期"] >= start_dt) & (df["净值日期"] <= end_dt)]

            if df.empty:
                raise AdapterError(f"基金 {fund_code} 在 {start_date} 至 {end_date} 期间无净值数据")

            # 转换为列表
            series = []
            for _, row in df.iterrows():
                nav_val = float(row.get("单位净值", 0))
                quality_flags = [QualityFlag.OK]
                if nav_val <= 0:
                    quality_flags = [QualityFlag.MISSING_FIELDS]

                series.append({
                    "fund_code": fund_code,
                    "nav_date": row["净值日期"].date(),
                    "nav": nav_val,
                    "acc_nav": float(row.get("累计净值", nav_val)),
                    "daily_pct": float(row.get("日增长率", 0).rstrip("%")) if row.get("日增长率") else None,
                    "quality_flags": quality_flags,
                })

            return AdapterResult(
                data=series,
                data_source=self.source,
                last_updated_at=datetime.utcnow(),
                quality_flags=[QualityFlag.OK],
            )

        except Exception as e:
            if isinstance(e, AdapterError):
                raise
            raise AdapterError(
                f"获取净值序列失败: {e}",
                can_fallback=True,
                fallback_source=DataSource.AKSHARE,
            )

    async def health_check(self) -> dict[str, bool | str]:
        """健康检查"""
        try:
            start = datetime.now()
            client = await self._get_client()

            # 尝试访问东方财富首页
            response = await client.get("https://fund.eastmoney.com/")
            latency_ms = int((datetime.now() - start).total_seconds() * 1000)

            return {
                "reachable": response.status_code == 200,
                "latency_ms": latency_ms,
                "error": None,
            }

        except Exception as e:
            return {
                "reachable": False,
                "latency_ms": 0,
                "error": str(e),
            }

    def _map_fund_type(self, raw_type: str) -> str:
        """映射基金类型"""
        type_map = {
            "开放式": FundType.MUTUAL,
            "封闭式": FundType.MUTUAL,
            "ETF": FundType.ETF,
            "LOF": FundType.LOF,
            "指数型": FundType.INDEX,
        }
        return type_map.get(raw_type, FundType.MUTUAL)


# 导入 pandas（AkShare 依赖）
import pandas as pd
