"""预测资格评估引擎。

从历史时序数据计算预测对象特征，按可配置规则判定 8 种资格状态，
并计算预测资格评分。对应需求 §5.2~§5.5。

八种状态：
  eligible / probation / cold / insufficient_history /
  poor_data_quality / low_predictability /
  manually_excluded / manually_included
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .rules import EligibilityRules, default_rules


# 八种状态枚举
STATUS_ELIGIBLE = "eligible"
STATUS_PROBATION = "probation"
STATUS_COLD = "cold"
STATUS_INSUFFICIENT_HISTORY = "insufficient_history"
STATUS_POOR_DATA_QUALITY = "poor_data_quality"
STATUS_LOW_PREDICTABILITY = "low_predictability"
STATUS_MANUALLY_EXCLUDED = "manually_excluded"
STATUS_MANUALLY_INCLUDED = "manually_included"

ALL_STATUSES = [
    STATUS_ELIGIBLE, STATUS_PROBATION, STATUS_COLD,
    STATUS_INSUFFICIENT_HISTORY, STATUS_POOR_DATA_QUALITY,
    STATUS_LOW_PREDICTABILITY, STATUS_MANUALLY_EXCLUDED,
    STATUS_MANUALLY_INCLUDED,
]


@dataclass
class EligibilityFeatures:
    """单个预测对象的历史特征。"""
    level: str                 # app / uri
    app_name: str
    uri_template: str
    total_requests: int
    active_days: int
    active_day_ratio: float
    nonzero_buckets: int
    nonzero_bucket_ratio: float
    data_completeness: float
    avg_daily_requests: float
    max_daily_requests: int
    avg_interarrival_minutes: float
    weekly_seasonality_score: float
    monthly_seasonality_score: float
    history_days: int
    # 附加诊断
    bucket_count: int
    missing_buckets: int
    night_concentration: float  # 夜间非零窗口占比（批处理特征）


@dataclass
class EligibilityResult:
    """评估结果。"""
    level: str
    app_name: str
    uri_template: str
    status: str
    history_days: int
    total_requests: int
    active_days: int
    data_completeness: float
    eligibility_score: float
    predictability: str
    reasons: List[str]
    features: Dict
    # 人工覆盖
    override_status: Optional[str] = None
    override_reason: Optional[str] = None
    override_by: Optional[str] = None
    override_at: Optional[str] = None
    # 活动专项纳入
    event_included: bool = False
    event_confidence: str = "not_applicable"


def _compute_features(series: pd.Series, timestamps: pd.Series,
                      level: str, app_name: str, uri_template: str,
                      lookback_days: int, freq_minutes: int) -> EligibilityFeatures:
    """从单个对象的时序计算特征。series 为 5min 粒度请求量。"""
    df = pd.DataFrame({"ts": timestamps, "v": series.values}).sort_values("ts")
    df = df.drop_duplicates("ts").reset_index(drop=True)

    total_requests = int(df["v"].sum())
    history_days = int(df["ts"].dt.day.nunique()) if len(df) else 0
    # 用时间跨度算覆盖天数
    if len(df):
        span_days = max((df["ts"].iloc[-1] - df["ts"].iloc[0]).total_seconds() / 86400.0, 1)
    else:
        span_days = 0
    history_days = max(history_days, int(round(span_days)))

    # 活跃天数：有非零请求的天数
    nonzero = df[df["v"] > 0]
    active_days = int(nonzero["ts"].dt.day.nunique()) if len(nonzero) else 0
    active_day_ratio = active_days / max(history_days, 1)

    bucket_count = len(df)
    nonzero_buckets = int((df["v"] > 0).sum())
    nonzero_bucket_ratio = nonzero_buckets / max(bucket_count, 1)

    # 数据完整率：实际桶数 / 期望桶数（观察窗口内的 5min 桶）
    expected_buckets = lookback_days * 24 * (60 // freq_minutes)
    data_completeness = min(bucket_count / max(expected_buckets, 1), 1.0)
    missing_buckets = max(expected_buckets - bucket_count, 0)

    avg_daily = total_requests / max(history_days, 1)
    max_daily = int(df.groupby(df["ts"].dt.date)["v"].sum().max()) if history_days else 0

    # 请求间隔
    if nonzero_buckets > 1:
        nz_ts = nonzero["ts"].reset_index(drop=True)
        gaps = nz_ts.diff().dropna().dt.total_seconds() / 60.0
        avg_inter = float(gaps.mean()) if len(gaps) else 0.0
    else:
        avg_inter = float("nan")

    # 周期性：按天聚合的自相关
    daily = df.groupby(df["ts"].dt.date)["v"].sum()
    weekly_score, monthly_score = _seasonality_scores(df)

    # 夜间集中度（批处理特征）：凌晨 0-6 点非零窗口占比
    hour = df["ts"].dt.hour
    night_mask = hour >= 0
    night_nz = ((df["v"] > 0) & night_mask).sum()
    night_concentration = float(night_nz / max(nonzero_buckets, 1))

    return EligibilityFeatures(
        level=level, app_name=app_name, uri_template=uri_template,
        total_requests=total_requests, active_days=active_days,
        active_day_ratio=round(active_day_ratio, 4),
        nonzero_buckets=nonzero_buckets,
        nonzero_bucket_ratio=round(nonzero_bucket_ratio, 4),
        data_completeness=round(data_completeness, 4),
        avg_daily_requests=round(avg_daily, 2),
        max_daily_requests=max_daily,
        avg_interarrival_minutes=round(avg_inter, 2) if not math.isnan(avg_inter) else None,
        weekly_seasonality_score=round(weekly_score, 4),
        monthly_seasonality_score=round(monthly_score, 4),
        history_days=history_days,
        bucket_count=bucket_count,
        missing_buckets=missing_buckets,
        night_concentration=round(night_concentration, 4),
    )


def _seasonality_scores(df: pd.DataFrame) -> tuple:
    """计算周周期与月周期强度（0~1）。

    用按天聚合序列，对星期哑变量回归的 R² 作为周周期强度；
    用按月聚合的趋势/自相关近似月周期。
    """
    if len(df) < 14:
        return 0.0, 0.0
    daily = df.groupby(df["ts"].dt.date)["v"].sum()
    if len(daily) < 14:
        return 0.0, 0.0
    dow = [d.weekday() if hasattr(d, "weekday") else getattr(d, "day_of_week", 0) for d in daily.index]
    y = daily.values.astype(float)
    # 周哑变量回归
    try:
        from numpy.linalg import lstsq
        dow_arr = np.array(dow)
        X = np.column_stack([np.ones(len(y))] + [(dow_arr == d).astype(float) for d in range(1, 7)])
        coef, *_ = lstsq(X, y, rcond=None)
        pred = X @ coef
        ss_res = float(np.sum((y - pred) ** 2))
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        weekly = max(0.0, 1.0 - ss_res / ss_tot) if ss_tot > 0 else 0.0
    except Exception:
        weekly = 0.0
    # 月周期：按月聚合的自相关
    monthly = df.groupby(df["ts"].dt.to_period("M"))["v"].sum()
    if len(monthly) >= 2:
        # 用月均值的离散度近似
        m = monthly.values.astype(float)
        # 自相关（lag-1）
        if len(m) > 1 and m.std() > 0:
            acf = float(np.corrcoef(m[:-1], m[1:])[0, 1])
            monthly = max(0.0, acf)
        else:
            monthly = 0.0
    else:
        monthly = 0.0
    return weekly, monthly


def _score_eligibility(feat: EligibilityFeatures, rules: EligibilityRules) -> float:
    """计算 0~100 资格评分（需求 §5.5）。"""
    w = rules.score_weights
    score = 0.0
    # 数据完整性
    score += w["completeness"] * min(feat.data_completeness / 0.99, 1.0) * 100
    # 历史覆盖
    cov = min(feat.history_days / rules.lookback_days, 1.0)
    score += w["history_coverage"] * cov * 100
    # 交易量充足程度（对数缩放）
    vol = min(math.log1p(feat.total_requests) / math.log1p(50000), 1.0)
    score += w["volume"] * vol * 100
    # 活跃天数
    act = min(feat.active_days / 30.0, 1.0)
    score += w["active_days"] * act * 100
    # 周期规律（周+月）
    seas = min((feat.weekly_seasonality_score + feat.monthly_seasonality_score) / 2.0, 1.0)
    score += w["seasonality"] * seas * 100
    # 稳定性（非零窗口比例适中 + 变异系数低）
    if feat.avg_daily_requests > 0:
        cv = _coefficient_of_variation(feat)
        stability = max(0.0, 1.0 - min(cv, 2.0) / 2.0)
    else:
        stability = 0.0
    score += w["stability"] * stability * 100
    return round(score, 2)


def _coefficient_of_variation(feat: EligibilityFeatures) -> float:
    """近似变异系数（用非零桶占比与活跃度推断稳定性）。"""
    # 简化：非零比例过低或日均过低视为不稳定
    if feat.avg_daily_requests <= 0:
        return 2.0
    # 基于日间波动的简化估计
    return 1.0 - feat.active_day_ratio + (1.0 - feat.nonzero_bucket_ratio)


def evaluate_object(series: pd.Series, timestamps: pd.Series,
                    level: str, app_name: str, uri_template: str,
                    rules: EligibilityRules = default_rules,
                    freq_minutes: int = 5,
                    override: Optional[Dict] = None,
                    event_included: bool = False) -> EligibilityResult:
    """评估单个预测对象。"""
    feat = _compute_features(series, timestamps, level, app_name, uri_template,
                             rules.lookback_days, freq_minutes)
    score = _score_eligibility(feat, rules)
    predictability = rules.band_for_score(score)

    status, reasons = _determine_status(feat, rules, predictability, score)

    # 人工覆盖优先
    if override and override.get("override_status") in ALL_STATUSES:
        status = override["override_status"]
        reasons.append(f"人工设置状态为 {status}")
        override_status = override["override_status"]
        override_reason = override.get("override_reason")
        override_by = override.get("override_by")
        override_at = override.get("override_at")
    else:
        override_status = None
        override_reason = None
        override_by = None
        override_at = None

    event_confidence = "low" if event_included else "not_applicable"

    return EligibilityResult(
        level=level, app_name=app_name, uri_template=uri_template,
        status=status, history_days=feat.history_days,
        total_requests=feat.total_requests, active_days=feat.active_days,
        data_completeness=feat.data_completeness,
        eligibility_score=score, predictability=predictability,
        reasons=reasons,
        features={
            "active_day_ratio": feat.active_day_ratio,
            "nonzero_buckets": feat.nonzero_buckets,
            "nonzero_bucket_ratio": feat.nonzero_bucket_ratio,
            "avg_daily_requests": feat.avg_daily_requests,
            "max_daily_requests": feat.max_daily_requests,
            "avg_interarrival_minutes": feat.avg_interarrival_minutes,
            "weekly_seasonality_score": feat.weekly_seasonality_score,
            "monthly_seasonality_score": feat.monthly_seasonality_score,
            "bucket_count": feat.bucket_count,
            "missing_buckets": feat.missing_buckets,
            "night_concentration": feat.night_concentration,
        },
        override_status=override_status, override_reason=override_reason,
        override_by=override_by, override_at=override_at,
        event_included=event_included, event_confidence=event_confidence,
    )


def _determine_status(feat: EligibilityFeatures, rules: EligibilityRules,
                      predictability: str, score: float) -> tuple:
    """按规则判定资格状态，返回 (status, reasons)。"""
    reasons: List[str] = []

    # 1. 历史覆盖不足
    if feat.history_days < rules.min_history_days_min:
        reasons.append(f"历史覆盖仅 {feat.history_days} 天，不足 {rules.min_history_days_min} 天")
        return STATUS_INSUFFICIENT_HISTORY, reasons

    # 2. 数据质量不合格
    if feat.data_completeness < rules.min_completeness:
        reasons.append(f"数据完整率 {feat.data_completeness:.2%} 低于 {rules.min_completeness:.0%}")
        return STATUS_POOR_DATA_QUALITY, reasons

    # 3. 历史覆盖 14~27 天：观察期
    if feat.history_days < rules.min_history_days_full:
        reasons.append(f"历史覆盖 {feat.history_days} 天，处于观察期（{rules.min_history_days_min}~{rules.min_history_days_full} 天）")
        return STATUS_PROBATION, reasons

    # 4. 冷系统：请求量极低且活跃天数少，无周期规律
    has_seasonality = (feat.weekly_seasonality_score >= rules.seasonality_acf_threshold
                       or feat.monthly_seasonality_score >= rules.seasonality_acf_threshold)
    if (feat.total_requests < rules.cold_total_requests
            and feat.active_days < rules.cold_active_days
            and not has_seasonality):
        reasons.append(
            f"历史请求量 {feat.total_requests} 过低，活跃天数 {feat.active_days} 较少，"
            f"未发现稳定交易时间规律")
        reasons.append("处理建议：保留监控，不参与常规交易量预测")
        return STATUS_COLD, reasons

    # 5. 低频但有稳定周期 → 允许进入人工评估
    if (feat.total_requests < rules.cold_total_requests
            and has_seasonality):
        reasons.append(
            f"请求量 {feat.total_requests} 较低，但检测到稳定周期规律，"
            f"建议人工评估是否纳入")
        return STATUS_PROBATION, reasons

    # 6. 低频接口（间隔长且不稳定）
    if (feat.total_requests < rules.probation_total_requests
            or feat.active_days < rules.probation_active_days):
        reasons.append(
            f"请求量 {feat.total_requests} / 活跃天数 {feat.active_days} "
            f"处于 probation 区间，数据基本可用仍在观察")
        return STATUS_PROBATION, reasons

    # 7. 具备稳定周期但整体规律弱 → low_predictability
    if predictability == "low":
        reasons.append("有流量但缺乏有效规律，预测质量可能较差")
        return STATUS_LOW_PREDICTABILITY, reasons

    # 8. 合格
    if (feat.total_requests >= rules.min_total_requests_eligible
            and feat.active_days >= rules.min_active_days_eligible
            and feat.data_completeness >= rules.min_completeness):
        return STATUS_ELIGIBLE, reasons

    # 兜底
    reasons.append(f"资格评分 {score}，未达合格阈值")
    return STATUS_PROBATION, reasons
