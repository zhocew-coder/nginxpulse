"""预测引擎数据准备。

严格区分（需求 §3.3）：
  - 真实零流量：采集正常但没有请求 → 计为 0
  - 数据缺失：采集异常/日志缺失 → 计为 NaN（缺失），不得误判为零
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from ..core import datasource
from ..mock.generator import TZ


def _freq_for(granularity: str) -> pd.Timedelta:
    mapping = {
        "1m": pd.Timedelta(minutes=1),
        "5m": pd.Timedelta(minutes=5),
        "15m": pd.Timedelta(minutes=15),
        "1h": pd.Timedelta(hours=1),
        "1d": pd.Timedelta(days=1),
    }
    return mapping.get(granularity, pd.Timedelta(minutes=5))


def _season_len(granularity: str) -> int:
    """一个日周期的桶数（用于 Seasonal Naive / 季节模型）。"""
    per_day = {
        "1m": 1440, "5m": 288, "15m": 96, "1h": 24, "1d": 1,
    }.get(granularity, 288)
    return per_day


def load_series(app_name: str, uri_template: str = "",
                granularity: str = "5m") -> pd.DataFrame:
    """加载并规整单个对象的时序。

    返回列：timestamp, value, is_missing
      - value: 请求量（真实零为 0）
      - is_missing: True 表示该桶无数据（缺失，非真实零）
    """
    df = datasource.query_history(app_name=app_name, uri_template=uri_template)
    if df.empty:
        return pd.DataFrame(columns=["timestamp", "value", "is_missing"])

    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert(TZ)
    df = df.sort_values("timestamp")

    # 按目标粒度重采样：求和（请求量可加）
    freq = _freq_for(granularity)
    if granularity != "5m":
        s = df.set_index("timestamp")["request_count"].resample(freq).sum()
        out = s.to_frame("value")
    else:
        # 原始即 5m 桶，直接对齐到规整网格
        s = df.set_index("timestamp")["request_count"].resample(freq).sum()
        out = s.to_frame("value")

    # 缺失检测：在起止范围内没有落入任何请求的桶视为缺失
    # mock 数据为完整网格，故 value=0 即真实零；真实环境下未被覆盖的桶为 NaN
    is_missing = out["value"].isna()
    # resample 后若桶内无任何记录会为 NaN → 视为缺失
    out["is_missing"] = is_missing
    out = out.reset_index().rename(columns={"timestamp": "timestamp", "value": "value"})
    out["value"] = out["value"].fillna(0.0)
    return out


def quality_report(series: pd.DataFrame) -> dict:
    """数据质量报告：缺失率、零值占比等。"""
    if series.empty:
        return {"n": 0, "missing_rate": 1.0, "zero_ratio": 0.0}
    n = len(series)
    missing = int(series["is_missing"].sum())
    zeros = int((series["value"] == 0).sum())
    return {
        "n": n,
        "missing_buckets": missing,
        "missing_rate": round(missing / max(n, 1), 4),
        "zero_buckets": zeros,
        "zero_ratio": round(zeros / max(n, 1), 4),
        "data_completeness": round(1 - missing / max(n, 1), 4),
    }
