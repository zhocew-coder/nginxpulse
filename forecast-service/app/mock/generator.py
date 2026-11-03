"""Mock 历史交易量时序生成器。

在无真实数据源时，生成符合银行数据中心业务语义的历史时序，
供准入过滤、预测、活动分析、回测等模块开发/测试/验证使用。

设计原则：
- 时间粒度 5 分钟（每天 288 桶），覆盖 ≥8 周（默认 70 天）。
- 多应用、多 URL，覆盖不同业务特征：
  - core：核心活跃应用，高流量 + 稳定周周期 + 日内双峰
  - standard：普通应用，中等流量 + 弱周期
  - batch：夜间批处理接口，仅凌晨有请求（白天为真实零流量）
  - lowfreq：低频接口，日均少量请求、时间不规律
  - cold：冷系统，极低流量、无周期、偶发
- 叠加：日内周期、周周期、缓慢趋势、节假日效应、活动峰值、噪声。
- 活动事件（双十一、双十二、月末批量、营销活动）只影响指定应用/URL，
  用于活动影响分析模块验证。
- 全程标识 MOCK，不得进入生产报告。

输出：长表 DataFrame [timestamp, app_name, uri_template, request_count]。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

# 时区：银行数据中心使用东八区
TZ = timezone(timedelta(hours=8))


@dataclass
class MockObject:
    """一个预测对象（应用或应用下的 URL）。"""
    level: str            # "app" | "uri"
    app_name: str
    uri_template: str     # "" 表示应用级聚合；否则为 URL 模板
    category: str         # core/standard/batch/lowfreq/cold
    base_rate: float      # 每 5 分钟平均请求量（基础水平）
    daily_pattern: List[float] = field(default_factory=list)  # 24 小时日内系数
    weekly_pattern: List[float] = field(default_factory=list)  # 7 天周系数
    noise_level: float = 0.15
    trend: float = 0.0     # 每日线性趋势（正=增长）
    # 活动影响：event_name -> uplift 系数
    event_uplifts: Dict[str, float] = field(default_factory=dict)


@dataclass
class MockEvent:
    """重大活动/业务事件。"""
    event_id: str
    event_name: str
    event_type: str        # marketing/batch/launch/promotion
    start: datetime
    end: datetime
    preheat_start: Optional[datetime]
    cooldown_end: Optional[datetime]
    target_apps: List[str]
    impact_level: str      # low/medium/high
    expected_uplift: Optional[float]
    status: str


# ---------------------------------------------------------------- 对象定义

def _daily_business_pattern(kind: str) -> List[float]:
    """生成日内 24 小时请求系数（1.0 为均值）。"""
    hrs = np.arange(24.0)
    if kind == "core":
        # 银行核心：早 9-11 高峰、午间低谷、下午 14-16 次峰、晚间回落
        base = 0.6 + 0.8 * np.exp(-((hrs - 10.0) ** 2) / 8.0) \
                 + 0.5 * np.exp(-((hrs - 15.0) ** 2) / 10.0)
        base += 0.3 * np.exp(-((hrs - 20.0) ** 2) / 12.0)
    elif kind == "standard":
        base = 0.7 + 0.5 * np.exp(-((hrs - 11.0) ** 2) / 12.0)
    elif kind == "batch":
        # 批处理：凌晨 1-4 点集中
        hrs_arr = np.arange(24.0)
        base = np.zeros(24)
        for h in range(1, 5):
            base += 1.0 + 0.5 * np.exp(-((hrs_arr - h) ** 2) / 2.0)
        base = np.maximum(base, 0.0)
    elif kind == "lowfreq":
        base = np.ones(24) * 0.5
    else:  # cold
        base = np.ones(24) * 0.2
    base = np.maximum(base, 0.0)
    mean = base.mean()
    if mean > 0:
        base = base / mean
    return base.tolist()


def _weekly_pattern(kind: str) -> List[float]:
    """周系数：周一到周日。"""
    if kind == "core":
        # 工作日高、周末低
        w = [1.3, 1.35, 1.3, 1.25, 1.2, 0.5, 0.45]
    elif kind == "standard":
        w = [1.1, 1.1, 1.1, 1.05, 1.0, 0.7, 0.65]
    elif kind == "batch":
        # 批处理周末也跑，接近均匀
        w = [1.0, 1.0, 1.0, 1.0, 1.0, 0.95, 0.95]
    elif kind == "lowfreq":
        w = [1.0] * 7
    else:
        w = [1.0] * 7
    mean = sum(w) / len(w)
    return [x / mean for x in w]


def build_mock_objects() -> List[MockObject]:
    """构造银行数据中心场景的预测对象清单。"""
    objs: List[MockObject] = []

    # ---- 核心应用（高流量、稳定周期）----
    core_apps = [
        ("core-banking", "手机银行核心", 420.0, 0.12, 0.01),
        ("core-payment", "支付清算核心", 380.0, 0.13, 0.012),
        ("core-card", "信用卡核心", 260.0, 0.14, 0.008),
    ]
    for app, _, base, noise, trend in core_apps:
        objs.append(MockObject(
            level="app", app_name=app, uri_template="", category="core",
            base_rate=base, daily_pattern=_daily_business_pattern("core"),
            weekly_pattern=_weekly_pattern("core"), noise_level=noise, trend=trend,
        ))
        # 核心应用下的关键 URL
        for uri, frac in [("/api/transaction/submit", 0.18), ("/api/account/query", 0.22),
                          ("/api/balance/get", 0.15), ("/api/transfer/confirm", 0.12)]:
            objs.append(MockObject(
                level="uri", app_name=app, uri_template=uri, category="core",
                base_rate=base * frac,
                daily_pattern=_daily_business_pattern("core"),
                weekly_pattern=_weekly_pattern("core"),
                noise_level=noise + 0.05, trend=trend,
            ))

    # ---- 普通应用 ----
    std_apps = [
        ("std-loan", "信贷系统", 90.0, 0.2, 0.005),
        ("std-crm", "客户关系管理", 70.0, 0.22, 0.0),
        ("std-report", "报表平台", 55.0, 0.25, -0.003),
    ]
    for app, _, base, noise, trend in std_apps:
        objs.append(MockObject(
            level="app", app_name=app, uri_template="", category="standard",
            base_rate=base, daily_pattern=_daily_business_pattern("standard"),
            weekly_pattern=_weekly_pattern("standard"), noise_level=noise, trend=trend,
        ))
        objs.append(MockObject(
            level="uri", app_name=app, uri_template="/api/main/entry", category="standard",
            base_rate=base * 0.3, daily_pattern=_daily_business_pattern("standard"),
            weekly_pattern=_weekly_pattern("standard"), noise_level=noise + 0.1, trend=trend,
        ))

    # ---- 夜间批处理应用（白天真实零流量）----
    objs.append(MockObject(
        level="app", app_name="batch-settlement", uri_template="", category="batch",
        base_rate=300.0, daily_pattern=_daily_business_pattern("batch"),
        weekly_pattern=_weekly_pattern("batch"), noise_level=0.1,
    ))
    objs.append(MockObject(
        level="uri", app_name="batch-settlement", uri_template="/api/batch/clearing",
        category="batch", base_rate=260.0,
        daily_pattern=_daily_business_pattern("batch"),
        weekly_pattern=_weekly_pattern("batch"), noise_level=0.1,
    ))

    # ---- 低频接口（日均少量、时间不规律）----
    objs.append(MockObject(
        level="uri", app_name="std-crm", uri_template="/api/legacy/archive",
        category="lowfreq", base_rate=0.15,
        daily_pattern=_daily_business_pattern("lowfreq"),
        weekly_pattern=_weekly_pattern("lowfreq"), noise_level=0.9,
    ))
    objs.append(MockObject(
        level="uri", app_name="std-loan", uri_template="/api/legacy/export",
        category="lowfreq", base_rate=0.2,
        daily_pattern=_daily_business_pattern("lowfreq"),
        weekly_pattern=_weekly_pattern("lowfreq"), noise_level=0.8,
    ))

    # ---- 冷系统（极低流量、无周期、偶发）----
    cold_apps = [
        ("cold-archive", "历史归档系统", 0.02),
        ("cold-oldbiz", "停用旧业务", 0.015),
        ("cold-test", "测试遗留系统", 0.01),
    ]
    for app, _, base in cold_apps:
        objs.append(MockObject(
            level="app", app_name=app, uri_template="", category="cold",
            base_rate=base, daily_pattern=_daily_business_pattern("cold"),
            weekly_pattern=_weekly_pattern("cold"), noise_level=1.5,
        ))
        objs.append(MockObject(
            level="uri", app_name=app, uri_template="/api/old/query",
            category="cold", base_rate=base * 0.5,
            daily_pattern=_daily_business_pattern("cold"),
            weekly_pattern=_weekly_pattern("cold"), noise_level=2.0,
        ))

    return objs


def build_mock_events(start: datetime, end: datetime) -> List[MockEvent]:
    """构造覆盖历史区间的重大活动/业务事件。"""
    events: List[MockEvent] = []

    def dt(day: int, h: int = 0, m: int = 0) -> datetime:
        return datetime(start.year, start.month, day, h, m, tzinfo=TZ)

    # 双十一营销活动（影响核心支付/信用卡）
    try:
        events.append(MockEvent(
            event_id="evt_2026_s11", event_name="2026双十一营销活动",
            event_type="marketing",
            start=datetime(start.year, 11, 11, 0, 0, tzinfo=TZ),
            end=datetime(start.year, 11, 11, 23, 59, tzinfo=TZ),
            preheat_start=datetime(start.year, 11, 1, 0, tzinfo=TZ),
            cooldown_end=datetime(start.year, 11, 13, 23, 59, tzinfo=TZ),
            target_apps=["core-payment", "core-card"],
            impact_level="high", expected_uplift=None, status="completed",
        ))
    except Exception:
        pass

    # 月末批量清算（每月最后一天，影响批处理）
    events.append(MockEvent(
        event_id="evt_monthly_batch", event_name="月末批量清算",
        event_type="batch",
        start=dt(28, 1), end=dt(28, 5),
        preheat_start=None, cooldown_end=dt(28, 6),
        target_apps=["batch-settlement", "core-banking"],
        impact_level="medium", expected_uplift=None, status="confirmed",
    ))

    # 信贷营销活动（影响信贷系统）
    events.append(MockEvent(
        event_id="evt_loan_promo", event_name="消费信贷推广活动",
        event_type="promotion",
        start=dt(15, 9), end=dt(17, 20),
        preheat_start=dt(14, 0), cooldown_end=dt(18, 0),
        target_apps=["std-loan"],
        impact_level="medium", expected_uplift=None, status="confirmed",
    ))

    return events


# ---------------------------------------------------------------- 序列生成

def _generate_series(obj: MockObject, start: datetime, end: datetime,
                     events: List[MockEvent]) -> pd.DataFrame:
    """为单个对象生成 [timestamp, request_count] 序列（纯 numpy 向量化）。"""
    # 基于 epoch 秒生成时间轴，避免 pandas 3.x 的隐式广播陷阱
    start_ts = int(start.timestamp())
    end_ts = int(end.timestamp())
    step = 5 * 60  # 5 分钟桶
    grid = np.arange(start_ts, end_ts + 1, step, dtype=np.int64)
    n = len(grid)
    ts = pd.to_datetime(grid, unit="s", utc=True).tz_convert(TZ)

    # 用 epoch 秒的整数运算提取时间特征（东八区 = UTC+8）
    local = grid + 8 * 3600
    day_of_week = ((local // 86400) % 7).astype(int)  # 0=周一（本地）
    day_of_year = ((local // 86400) % 365).astype(int)
    seconds_in_day = local % 86400
    hrs = seconds_in_day / 3600.0  # 小时（浮点，用于日内插值）

    daily = np.array(obj.daily_pattern or [1.0] * 24)
    weekly = np.array(obj.weekly_pattern or [1.0] * 7)

    # 日内系数：按小时整数取值 + 相邻线性插值
    hr_idx = np.minimum(23, (seconds_in_day // 3600).astype(int))
    frac = (seconds_in_day % 3600) / 3600.0
    d_floor = daily[hr_idx]
    d_ceil = daily[np.minimum(23, hr_idx + 1)]
    day_coef = d_floor * (1 - frac) + d_ceil * frac
    week_coef = weekly[day_of_week]

    # 缓慢趋势 + 轻微月度季节性
    days_elapsed = (grid - start_ts) / 86400.0
    trend_coef = 1.0 + obj.trend * days_elapsed
    month_seas = 1.0 + 0.08 * np.sin(2 * math.pi * day_of_year / 365.0)

    rate = obj.base_rate * day_coef * week_coef * trend_coef * month_seas

    # 活动影响（全部基于 epoch 秒的布尔索引）
    for evt in events:
        if obj.app_name not in evt.target_apps:
            continue
        uplift = obj.event_uplifts.get(evt.event_id, 0.0)
        if uplift <= 0:
            continue
        evt_start = int(evt.start.timestamp())
        evt_end = int(evt.end.timestamp()) if evt.end else end_ts + 1

        # 预热期：渐进提升
        if evt.preheat_start is not None:
            pre_s = int(evt.preheat_start.timestamp())
            preheat_mask = (grid >= pre_s) & (grid < evt_start)
            if preheat_mask.any():
                span = max(evt_start - pre_s, 1)
                prog = (grid[preheat_mask] - pre_s) / span
                rate[preheat_mask] *= (1.0 + uplift * 0.5 * prog)

        # 正式期：峰值增幅
        active_mask = (grid >= evt_start) & (grid <= evt_end)
        rate[active_mask] *= (1.0 + uplift)

        # 回落期：衰减
        if evt.cooldown_end is not None:
            cool_end = int(evt.cooldown_end.timestamp())
            cool_mask = (grid > evt_end) & (grid <= cool_end)
            if cool_mask.any():
                span = max(cool_end - evt_end, 1)
                prog = (grid[cool_mask] - evt_end) / span
                rate[cool_mask] *= (1.0 + uplift * (1.0 - prog) ** 2)

    # 噪声（保证非负、可产生真实零值用于低频/批处理）
    noise = np.random.default_rng(
        hash((obj.app_name, obj.uri_template)) & 0xFFFFFFFF
    ).normal(1.0, obj.noise_level, n)
    rate = rate * noise

    # 批处理/低频/冷：稀疏化，制造真实零值
    if obj.category == "batch":
        # 非凌晨时段置零（真实零流量，非缺失）
        offpeak = (hrs < 1) | (hrs >= 5)
        rate[offpeak] = 0.0
    elif obj.category == "lowfreq":
        # 每天仅少量桶有请求：随机稀疏
        rng = np.random.default_rng(
            hash((obj.app_name, obj.uri_template, "lf")) & 0xFFFFFFFF)
        keep = rng.random(n) < 0.05
        rate = np.where(keep, rate, 0.0)
    elif obj.category == "cold":
        rng = np.random.default_rng(
            hash((obj.app_name, obj.uri_template, "cold")) & 0xFFFFFFFF)
        keep = rng.random(n) < 0.02
        rate = np.where(keep, rate, 0.0)

    counts = np.maximum(np.round(rate), 0.0).astype(np.int64)

    df = pd.DataFrame({"timestamp": ts, "request_count": counts})
    df.insert(1, "app_name", obj.app_name)
    df.insert(2, "uri_template", obj.uri_template)
    df.insert(3, "category", obj.category)
    df.insert(4, "data_source", "mock")
    return df


def generate(history_days: int = 70, bucket_minutes: int = 5,
             seed: int = 20261102) -> pd.DataFrame:
    """生成完整 Mock 时序，返回长表。"""
    np.random.seed(seed)
    end = datetime.now(TZ).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=history_days)

    objs = build_mock_objects()
    events = build_mock_events(start, end)

    # 给核心支付/信用卡对象配置双十一等事件增幅
    uplift_map = {
        ("core-payment", ""): {"evt_2026_s11": 1.8},
        ("core-payment", "/api/transaction/submit"): {"evt_2026_s11": 2.2},
        ("core-card", ""): {"evt_2026_s11": 1.6},
        ("std-loan", ""): {"evt_loan_promo": 1.4},
        ("std-loan", "/api/main/entry"): {"evt_loan_promo": 1.5},
        ("batch-settlement", ""): {"evt_monthly_batch": 2.5},
        ("batch-settlement", "/api/batch/clearing"): {"evt_monthly_batch": 2.8},
        ("core-banking", ""): {"evt_monthly_batch": 1.3},
    }
    for obj in objs:
        key = (obj.app_name, obj.uri_template)
        if key in uplift_map:
            obj.event_uplifts = uplift_map[key]

    frames = [_generate_series(o, start, end, events) for o in objs]
    df = pd.concat(frames, ignore_index=True)
    df["granularity"] = f"{bucket_minutes}m"
    return df


if __name__ == "__main__":
    df = generate(70, 5)
    print(f"生成 {len(df)} 行，对象数 {df.groupby(['app_name','uri_template']).ngroups}")
    print(df.head(3).to_string())
    print("各应用请求量合计：")
    print(df.groupby("app_name")["request_count"].sum().sort_values().to_string())
