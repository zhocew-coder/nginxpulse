"""数据源抽象：Mock 时序 vs 真实数据库。

USE_MOCK=true 时从 mock 生成器取数；false 时从 NginxPulse PostgreSQL 聚合。
两者返回统一的长表 DataFrame，供下游引擎无感使用。
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from ..core.config import settings
from ..mock import generator


_mock_cache: Optional[pd.DataFrame] = None


def _get_mock_series() -> pd.DataFrame:
    """生成/缓存 mock 时序长表。"""
    global _mock_cache
    if _mock_cache is None:
        _mock_cache = generator.generate(
            history_days=settings.mock_history_days,
            bucket_minutes=settings.mock_bucket_minutes,
            seed=settings.mock_seed,
        )
    return _mock_cache


def _get_real_series() -> pd.DataFrame:
    """从真实 PostgreSQL 聚合时序（按需实现，此处兜底报错）。

    真实路径需从 f002_nginx_logs 按 5min 桶聚合到
    [timestamp, app_name(host), uri_template, request_count]。
    """
    raise NotImplementedError(
        "USE_MOCK=false 需要接入真实 NginxPulse 日志聚合，"
        "当前版本仅支持 mock 数据源"
    )


def get_history_series() -> pd.DataFrame:
    """返回统一的历史时序长表。"""
    if settings.use_mock:
        return _get_mock_series()
    return _get_real_series()


def query_history(app_name: Optional[str] = None,
                  uri_template: Optional[str] = None,
                  granularity: str = "5m") -> pd.DataFrame:
    """按条件过滤历史时序。"""
    df = get_history_series()
    if app_name:
        df = df[df["app_name"] == app_name]
    if uri_template:
        if uri_template == "__ALL__":
            pass  # 返回该应用全部
        else:
            df = df[df["uri_template"] == uri_template]
    return df.copy()
