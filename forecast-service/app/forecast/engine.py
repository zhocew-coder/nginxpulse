"""常规交易量预测引擎（阶段三）。

流程：
  1. 加载历史时序（区分真实零流量与数据缺失）
  2. 检查预测资格（需求 §7.7：不合格对象默认拒绝常规预测，返回明确原因）
  3. 模型选择（auto 时按滚动回测 MAE 选优）
  4. 生成点预测 + 预测区间（区间来自残差分位数，非 LLM 生成）
  5. 输出基线预测（baseline），阶段四在此基础上叠加活动增量

需求 §6.4：peak_qps 只有在底层统计数据具备足够细粒度时才输出，
不能用 5 分钟平均 QPS 代替真实瞬时峰值 —— 此处统一为 null 并说明。
"""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from ..core.config import settings
from ..core import datasource
from ..eligibility import engine as elig_engine
from ..eligibility.rules import default_rules
from ..storage import eligibility_store, forecast_store
from . import dataset
from . import event_impact
from .backtest import rolling_backtest, select_best_model
from .models import build_model, prediction_intervals

TZ = timezone(timedelta(hours=8))

# 允许进入常规预测的状态
ALLOWED_STATUSES = {"eligible", "probation", "manually_included"}


def _clean_nan(obj):
    """递归把 NaN/Inf 转为 None。

    冷系统（全零序列）会使 WAPE/sMAPE 分母为 0 产生 NaN，
    而 JSON 不接受 NaN（FastAPI 与 PostgreSQL jsonb 均会报错）。
    """
    if isinstance(obj, dict):
        return {k: _clean_nan(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean_nan(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def _horizon_buckets(horizon: str, granularity: str) -> int:
    """把 horizon（如 24h / 7d）换算为桶数。"""
    unit = horizon[-1]
    try:
        amount = int(horizon[:-1])
    except ValueError:
        amount = 24
    minutes = {"m": 1, "h": 60, "d": 1440}.get(unit, 60) * amount
    per = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "1d": 1440}.get(granularity, 5)
    return max(1, minutes // per)


def _granularity_seconds(granularity: str) -> int:
    return {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "1d": 86400}.get(
        granularity, 300)


def check_eligibility(level: str, app_name: str, uri_template: str) -> Dict:
    """检查对象预测资格，返回 (allowed, status, reasons, risk_flags)。"""
    override = eligibility_store.get_override(level, app_name, uri_template)
    df = datasource.query_history(app_name=app_name,
                                  uri_template=uri_template or "__ALL__")
    if df.empty:
        return {"allowed": False, "status": "unknown",
                "reasons": ["未找到该对象的历史时序数据"], "risk_flags": []}
    res = elig_engine.evaluate_object(
        series=df["request_count"], timestamps=df["timestamp"],
        level=level, app_name=app_name, uri_template=uri_template,
        rules=default_rules, freq_minutes=settings.mock_bucket_minutes,
        override=override,
    )
    risk_flags: List[str] = []
    allowed = res.status in ALLOWED_STATUSES
    if res.status == "manually_included":
        risk_flags.append("人工强制纳入，需标注风险")
    if res.status == "probation":
        risk_flags.append("观察期对象，预测结果仅供参考")
    if res.status == "cold":
        risk_flags.append("冷系统：常规基线不可靠，如需预测请走活动专项")
    return {
        "allowed": allowed,
        "status": res.status,
        "reasons": res.reasons,
        "risk_flags": risk_flags,
        "predictability": res.predictability,
        "eligibility_score": res.eligibility_score,
    }


def run_forecast(app_name: str, uri_template: str = "",
                 metric: str = "request_count",
                 granularity: str = "5m",
                 horizon: str = "24h",
                 scenario: str = "baseline",
                 model_strategy: str = "auto",
                 include_interval: bool = True,
                 force: bool = False,
                 event=None) -> Dict:
    """执行一次预测，返回结果字典。"""
    level = "uri" if uri_template else "app"
    series = dataset.load_series(app_name, uri_template, granularity)
    if series.empty or len(series) < 10:
        return {"error": "历史数据不足，无法预测", "app_name": app_name}

    # 资格校验（需求 §7.7）
    elig = check_eligibility(level, app_name, uri_template)
    if not elig["allowed"] and not force:
        return {
            "error": "对象不符合常规预测准入条件",
            "app_name": app_name,
            "uri_template": uri_template,
            "status": elig["status"],
            "reasons": elig["reasons"],
            "hint": "如需预测，请通过活动专项预测或人工强制纳入（force=true）",
        }

    y = series["value"].to_numpy(dtype=float)
    ts = series["timestamp"]
    season = dataset._season_len(granularity)
    horizon_n = _horizon_buckets(horizon, granularity)
    secs = _granularity_seconds(granularity)

    # 模型选择
    chosen = model_strategy
    backtest = {}
    if model_strategy == "auto":
        # 数据量足够时才跑回测，否则直接用轻量模型
        if len(y) >= season * 8:
            try:
                backtest = rolling_backtest(
                    y, ts, season=season, horizon=min(horizon_n, season),
                    folds=3, strategies=["seasonal_naive", "lightgbm"],
                )
            except Exception:
                backtest = {}
        chosen = select_best_model(backtest) if backtest else (
            "lightgbm" if len(y) >= season * 4 else "seasonal_naive")
    elif model_strategy not in ("seasonal_naive", "ets", "sarima", "lightgbm"):
        chosen = "lightgbm"

    # 拟合并预测
    model = build_model(chosen).fit(y, ts, season)
    try:
        point = np.asarray(model.predict(horizon_n), dtype=float)
    except Exception:
        point = prediction_intervals(y, y[-1:], season)[0]  # 兜底
    point = np.nan_to_num(point, nan=float(np.mean(y[-season:])), posinf=0.0)
    point = np.maximum(point, 0.0)

    if include_interval:
        # 从回测中提取所选模型的 MAE 用于区间校准
        model_mae = None
        if backtest and chosen in backtest:
            model_mae = backtest[chosen].get("mae")
        model_resid = model.in_sample_residuals()
        lower, upper = prediction_intervals(y, point, season,
                                            model_mae=model_mae,
                                            model_resid=model_resid)
    else:
        lower, upper = point, point

    # 时间轴：最后一个已知时间 + 步长
    last_ts = pd.to_datetime(ts.iloc[-1])
    step = pd.Timedelta(seconds=secs)
    future_ts = [last_ts + step * (i + 1) for i in range(horizon_n)]

    points: List[Dict] = []
    for i in range(horizon_n):
        base_val = float(point[i])
        pts = {
            "timestamp": future_ts[i].isoformat(),
            "baseline_forecast": round(base_val, 2),
            "event_increment": 0.0,          # 阶段四填充
            "event_adjusted_forecast": round(base_val, 2),
            "lower_bound": round(float(max(lower[i], 0.0)), 2),
            "upper_bound": round(float(max(upper[i], 0.0)), 2),
            "avg_qps": round(base_val / secs, 4),
            # 需求 §6.4：5min 聚合无法得到真实瞬时峰值，故为 null
            "peak_qps": None,
        }
        points.append(pts)

    # ---- 活动影响（阶段四，需求 §4.4）----
    # EventAdjusted(t) = Baseline(t) + EventEffect(t)
    # 增幅必须来自历史实测或活动计划参数；数据不足时增量为 0 并标注，绝不编造。
    event_info = None
    if event is not None and scenario in ("event_adjusted", "scenario_compare"):
        base_points = [dict(p) for p in points]
        up = event_impact.estimate_uplift(app_name, uri_template, event)
        if up["uplift"] is not None:
            points = event_impact.apply_event_effect(
                base_points, event, up["uplift"], "baseline")
        event_info = {
            "event_id": getattr(event, "event_id", None),
            "event_name": getattr(event, "event_name", None),
            "event_type": getattr(event, "event_type", None),
            "target_apps": getattr(event, "target_apps", []),
            "uplift_estimate": up,
            "diff_analysis": event_impact.diff_analysis(
                base_points, points, event),
            "scenarios": event_impact.scenario_compare(
                base_points, event, up["uplift"]),
        }

    quality = dataset.quality_report(series)
    forecast_id = f"fc_{uuid.uuid4().hex[:12]}"

    base_total = float(sum(p["baseline_forecast"] for p in points))
    adj_arr = np.array([p["event_adjusted_forecast"] for p in points])
    inc_total = float(sum(p["event_increment"] for p in points))

    result = {
        "forecast_id": forecast_id,
        "app_name": app_name,
        "uri_template": uri_template,
        "metric": metric,
        "granularity": granularity,
        "horizon": horizon,
        "scenario": scenario,
        "model": chosen,
        "model_strategy": model_strategy,
        "points": points,
        "summary": {
            "total_baseline": round(base_total, 2),
            "total_event_adjusted": round(float(adj_arr.sum()), 2),
            "total_event_increment": round(inc_total, 2),
            "peak_baseline": round(float(np.max(point)), 2),
            "peak_event_adjusted": round(float(adj_arr.max()), 2),
            "peak_timestamp": future_ts[int(np.argmax(adj_arr))].isoformat(),
            "peak_qps": None,
            "avg_qps": round(float(np.mean(point)) / secs, 4),
        },
        "quality": quality,
        "backtest": backtest,
        "eligibility": {
            "status": elig["status"],
            "predictability": elig.get("predictability"),
            "score": elig.get("eligibility_score"),
        },
        "risk_flags": elig["risk_flags"],
        "event": event_info,
        "data_source": "mock" if settings.use_mock else "real",
        "generated_at": datetime.now(TZ).isoformat(),
        "history_range": {
            "start": pd.to_datetime(ts.iloc[0]).isoformat(),
            "end": last_ts.isoformat(),
            "buckets": len(y),
        },
    }
    result = _clean_nan(result)
    forecast_store.save_forecast(result)
    return result
