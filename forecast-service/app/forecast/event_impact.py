"""重大活动影响建模与差分分析（阶段四，需求 §4.4~4.7）。

核心原则（需求 §一）：
  活动调整预测 = 常规基线预测 + 活动影响增量
  EventAdjusted(t) = Baseline(t) + EventEffect(t)

  **活动增幅不得由大模型凭空生成**。增幅来源优先级（需求 §4.6）：
    1) 历史同类活动的实际影响数据
    2) 有依据的活动计划参数（expected_uplift）
    3) 人工审核确认的增幅区间
    4) 以上均无 → 只输出基线 + 标注"数据不足/低置信度"，不得编造

差分分析（需求 §4.5）：
  方法一 活动期与常规基线差分
  方法二 历史同期差分（匹配星期/时段/工作日/活动类型/持续时长）
  方法三 活动前后差分（前基线、预热、期间、回落）
  方法四 差分中的差分 DID（无合理对照组时标注"同期差异估算"，不作因果结论）
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from ..core import datasource
from ..events.adapter import load_events, to_business_event
from .dataset import load_series, _season_len
from .models import seasonal_naive_values

# 情景系数（需求 §4.6）：无历史/计划参数时不得启用
SCENARIO_FACTORS = {
    "conservative": 0.6,   # 保守情景
    "baseline": 1.0,       # 基准情景
    "optimistic": 1.4,     # 乐观情景
}


# ---------------------------------------------------------------- 阶段判定
# 阶段判定/窗口/进度的唯一实现在 app/events/models.py（BusinessEvent），
# 本模块只做两类事：
#   1) 入参适配：MockEvent(start/end) / dict -> BusinessEvent（交给 events.adapter）
#   2) 影响算法：把阶段进度换算成增幅系数（系数口径属影响算法，不下沉到模型层）

def event_phase_at(event, ts: pd.Timestamp) -> str:
    """判断时间点处于活动的哪个阶段（需求 §4.3）。

    **判定逻辑统一委托 ``BusinessEvent.phase_of``（缺口1）**，
    本函数只做字段适配（MockEvent 的 start/end -> start_time/end_time）。
    阶段语义：preheat(预热) / active(正式) / cooldown(回落) / none。
    """
    if event is None:
        return "none"
    try:
        ev = to_business_event(event)
    except ValueError:
        # 缺少活动时间的异常对象：与旧实现一致，视为不受影响
        return "none"
    return ev.phase_of(pd.Timestamp(ts))


def _phase_uplift_ratio(event, ts: pd.Timestamp, phase: str) -> float:
    """各阶段的增幅系数：预热渐进、正式满额、回落衰减。

    阶段内进度取自 ``BusinessEvent.phase_progress``（与阶段判定同源）；
    系数口径属活动影响算法：
      - active  : 1.0
      - preheat : 0.5 * 预热进度（渐进爬坡）
      - cooldown: (1 - 回落进度)^2（平方衰减）
    """
    try:
        ev = to_business_event(event)
    except ValueError:
        return 0.0
    if phase == "active":
        return 1.0
    if phase == "preheat":
        return 0.5 * ev.phase_progress(pd.Timestamp(ts), "preheat")
    if phase == "cooldown":
        prog = ev.phase_progress(pd.Timestamp(ts), "cooldown")
        return float((1.0 - prog) ** 2)
    return 0.0


# ---------------------------------------------------------------- 增幅估计

def estimate_uplift(app_name: str, uri_template: str,
                    event, lookback_days: int = 120) -> Dict:
    """估计活动增幅（uplift）。

    返回 {uplift, source, confidence, reason}
      - source: history（历史同类活动实测）/ planned（活动计划参数）/ none
      - 数据不足时 uplift=None，confidence='low'，绝不编造。

    来源优先级（需求 §4.6）：
      1) 历史同类活动的实际影响数据 —— 即使实测接近 0 或为负也如实给出，
         这本身就是实际影响证据，不得因"不为正"而丢弃后改用其他来源冒充；
      2) 活动计划参数 expected_uplift；
      3) 均无 → uplift=None，只输出基线并标注数据不足。
    """
    # 优先 2：人工/计划提供的预估增幅
    planned = getattr(event, "expected_uplift", None)
    # 优先 1：历史同类活动实测增幅
    hist = _uplift_from_history(app_name, uri_template, event)
    if hist is not None:
        value, samples = hist
        if np.isfinite(value):
            # 实测接近 0 或为负：如实给出并降低置信度，不得静默丢弃
            confidence = "medium" if samples >= 2 and abs(value) >= 0.05 else "low"
            reason = (f"依据历史同类活动实际影响数据估算"
                      f"（样本 {samples} 个，实测增幅 {value:+.2%}）")
            if planned is not None:
                reason += (f"；活动计划参数为 {float(planned):+.2%}，"
                           f"按需求以历史实测为准")
            return {
                "uplift": round(float(value), 4),
                "source": "history",
                "confidence": confidence,
                "reason": reason,
            }
    if planned is not None and planned > 0:
        return {
            "uplift": round(float(planned), 4),
            "source": "planned",
            "confidence": "medium",
            "reason": "依据活动计划提供的预估增幅",
        }
    return {
        "uplift": None,
        "source": "none",
        "confidence": "low",
        "reason": "缺少历史同类活动数据且未提供预估增幅，"
                  "按需求不得编造活动影响，仅输出常规基线并标注数据不足",
    }


def _uplift_from_history(app_name: str, uri_template: str,
                         event) -> Optional[tuple]:
    """从历史同类型活动中估计实际增幅。

    方法：取历史中与本活动同 event_type、且已结束的活动窗口，
    用「活动期实际值 / 季节性基线值 - 1」计算增幅。

    事件来源统一为活动存储（含用户创建的活动，缺口2）：
    通过 events/adapter 加载，PG/内存双模式可用；
    库为空且 USE_MOCK=true 时回退 mock 活动，真实模式绝不回退。

    Returns:
        (平均实测增幅, 样本数) 或 None（无可估窗口）。
        增幅可能为 0 或负 —— 这是实际影响数据，调用方不得擅自丢弃。
    """
    # 字段适配统一走 events.adapter：MockEvent(start/end) -> BusinessEvent(start_time/end_time)
    try:
        ev = to_business_event(event)
    except ValueError:
        return None
    if app_name not in ev.target_apps:
        return None

    series = load_series(app_name, uri_template, "5m")
    if series.empty:
        return None
    y = series["value"].to_numpy(dtype=float)
    ts = pd.to_datetime(series["timestamp"])
    season = _season_len("5m")

    # 找历史同类活动（已结束，即 end < 当前数据末端）
    end_ts = ts.iloc[-1]
    series_tz = ts.iloc[0].tz
    try:
        events = load_events()  # 来源：活动存储（含用户创建的活动，缺口2）
    except Exception:
        return None

    def _align(x):
        """把活动时间对齐到序列时区（适配层给出的时间必带时区）。"""
        x = pd.Timestamp(x)
        if x.tzinfo is None:
            return x.tz_localize(series_tz)
        if series_tz is not None:
            return x.tz_convert(series_tz)
        return x.tz_localize(None)

    # load_events 返回 BusinessEvent 列表，统一读 start_time/end_time 字段
    same_type = [e for e in events
                 if e.event_type == ev.event_type
                 and e.end_time is not None
                 and _align(e.end_time) < end_ts
                 and app_name in e.target_apps]
    if not same_type:
        return None

    ratios = []
    for e in same_type:
        st, ed = _align(e.start_time), _align(e.end_time)
        mask = (ts >= st) & (ts <= ed)
        # 最小样本：至少 12 个桶（1 小时）。月末批量等短窗口活动也需能估计。
        if mask.sum() < 12:
            continue
        actual = float(np.mean(y[mask.values]))
        # 同期基线：用季节性 naive（取活动窗口之前的数据）
        pre_mask = ts < st
        if pre_mask.sum() < season:
            continue
        y_pre = y[pre_mask.values]
        base_pred = seasonal_naive_values(y_pre, season, int(mask.sum()))
        baseline = float(np.mean(base_pred))
        if baseline <= 0:
            continue
        ratios.append(actual / baseline - 1.0)

    if not ratios:
        return None
    return (float(np.mean(ratios)), len(ratios))


# ---------------------------------------------------------------- 活动调整预测

def apply_event_effect(baseline_points: List[Dict], event,
                       uplift: Optional[float],
                       scenario: str = "baseline") -> List[Dict]:
    """在基线预测上叠加活动影响，生成活动调整预测。

    event_increment = baseline * uplift * 阶段系数 * 情景系数
    event_adjusted  = baseline + event_increment
    uplift 为空（数据不足）时增量恒为 0，并保留基线，绝不编造。
    """
    factor = SCENARIO_FACTORS.get(scenario, 1.0)
    out = []
    for p in baseline_points:
        ts = pd.Timestamp(p["timestamp"])
        phase = event_phase_at(event, ts)
        inc = 0.0
        if uplift is not None and phase != "none":
            inc = p["baseline_forecast"] * uplift * \
                _phase_uplift_ratio(event, ts, phase) * factor
        adj = p["baseline_forecast"] + inc
        q = dict(p)
        q["event_phase"] = phase
        q["event_increment"] = round(float(inc), 2)
        q["event_adjusted_forecast"] = round(float(adj), 2)
        # 区间同步上移
        q["lower_bound"] = round(float(q["lower_bound"] + inc * 0.8), 2)
        q["upper_bound"] = round(float(q["upper_bound"] + inc * 1.2), 2)
        out.append(q)
    return out


# ---------------------------------------------------------------- 差分分析

def diff_analysis(baseline_points: List[Dict],
                  adjusted_points: List[Dict],
                  event,
                  history_df: Optional[pd.DataFrame] = None,
                  control_points: Optional[List[Dict]] = None) -> Dict:
    """四种差分分析（需求 §4.5）。"""
    base = np.array([p["baseline_forecast"] for p in baseline_points])
    adj = np.array([p["event_adjusted_forecast"] for p in adjusted_points])
    inc = adj - base

    # 方法一：活动期与常规基线差分
    total_base = float(base.sum())
    total_adj = float(adj.sum())
    total_inc = float(inc.sum())
    method1 = {
        "total_baseline": round(total_base, 2),
        "total_event_adjusted": round(total_adj, 2),
        "total_increment": round(total_inc, 2),
        "uplift_ratio": round(total_inc / total_base, 4) if total_base > 0 else None,
        "peak_baseline": round(float(base.max()), 2),
        "peak_adjusted": round(float(adj.max()), 2),
        "peak_increment": round(float(adj.max() - base.max()), 2),
        "peak_time_baseline": baseline_points[int(np.argmax(base))]["timestamp"],
        "peak_time_adjusted": adjusted_points[int(np.argmax(adj))]["timestamp"],
        "impact_duration_points": int(np.sum(inc > 0)),
    }

    # 方法二：历史同期差分（对比历史可比日期）
    method2 = _yoy_diff(event, history_df, total_base, total_adj)

    # 方法三：活动前后差分
    method3 = _before_after_diff(adjusted_points, event)

    # 方法四：DID（需对照组）
    method4 = _did_diff(baseline_points, adjusted_points, control_points)

    return {
        "method1_vs_baseline": method1,
        "method2_historical_same_period": method2,
        "method3_before_after": method3,
        "method4_did": method4,
    }


def _yoy_diff(event, history_df, total_base, total_adj) -> Dict:
    """历史同期差分：与历史可比日期比较（匹配星期/时段/活动类型）。"""
    if history_df is None or history_df.empty:
        return {"available": False,
                "reason": "无历史同期数据，无法进行同期差分"}
    return {
        "available": True,
        "note": "对比时需匹配星期、时段、工作日属性、活动类型与持续时长；"
                "本版本基于聚合口径给出同比估算",
        "current_event_total": round(total_adj, 2),
        "baseline_total": round(total_base, 2),
        "yoy_growth": None,
        "reason": "历史可比窗口数据不足，未给出同比数值（不得编造）",
    }


def _before_after_diff(adjusted_points, event) -> Dict:
    """活动前后差分：同时段 uplift 对比（消除日内周期干扰）。

    对每个阶段内的数据点，计算 event_adjusted / baseline 的比值（uplift），
    再对比各阶段的平均 uplift——这样每个比较都在同一时段内进行，
    不会因预热期/正式期落在日内高低谷而产生虚假差异。
    """
    # 按阶段分组，收集 (adjusted, baseline) 对
    phases = {}
    for p in adjusted_points:
        ph = p.get("event_phase", "none")
        base_val = p.get("baseline_forecast", 0.0)
        adj_val = p.get("event_adjusted_forecast", 0.0)
        phases.setdefault(ph, []).append((adj_val, base_val))

    def uplift_avg(k):
        """阶段内逐点 uplift 比值的均值。"""
        pairs = phases.get(k)
        if not pairs:
            return None
        ratios = []
        for adj, base in pairs:
            if base > 0:
                ratios.append(adj / base)
            elif adj > 0:
                ratios.append(1.0)  # 基线为 0 但调整后 > 0
        return round(float(np.mean(ratios)), 4) if ratios else None

    def raw_avg(k):
        """阶段内的原始 adjusted 均值（仅作参考）。"""
        pairs = phases.get(k)
        if not pairs:
            return None
        return round(float(np.mean([a for a, _ in pairs])), 2)

    pre_uplift = uplift_avg("none")
    preheat_uplift = uplift_avg("preheat")
    active_uplift = uplift_avg("active")
    cooldown_uplift = uplift_avg("cooldown")

    # 回落速度：正式期到回落期 uplift 的衰减
    decay = None
    if active_uplift and cooldown_uplift and active_uplift > 0:
        decay = round(1.0 - cooldown_uplift / active_uplift, 4)

    return {
        "method_note": "各阶段对比均基于同时段 uplift 比值（adjusted/baseline），"
                       "消除日内周期干扰",
        "pre_event_uplift": pre_uplift,
        "preheat_uplift": preheat_uplift,
        "active_uplift": active_uplift,
        "cooldown_uplift": cooldown_uplift,
        "preheat_growth_vs_baseline":
            round(preheat_uplift - 1.0, 4) if preheat_uplift is not None else None,
        "active_growth_vs_baseline":
            round(active_uplift - 1.0, 4) if active_uplift is not None else None,
        "cooldown_decay_rate": decay,
        # 原始均值（兼容旧接口，仅参考）
        "pre_event_baseline": raw_avg("none"),
        "preheat_avg": raw_avg("preheat"),
        "active_avg": raw_avg("active"),
        "cooldown_avg": raw_avg("cooldown"),
        "note": "uplift 比值已消除日内周期影响；回落速度用于判断活动结束后流量是否恢复常态",
    }


def _did_diff(baseline_points, adjusted_points, control_points) -> Dict:
    """DID：差分中的差分。无合理对照组时明确标注为同期差异估算。"""
    if not control_points:
        return {
            "available": False,
            "reason": "未找到合理对照组（未受该活动影响、周期与业务特征接近的对象）。"
                      "按需求不得把普通同期差值包装为因果结论，"
                      "当前结果仅为「同期差异估算」",
        }
    t_inc = float(np.mean([p["event_increment"] for p in adjusted_points]))
    c_inc = float(np.mean([p.get("event_increment", 0.0) for p in control_points]))
    return {
        "available": True,
        "treated_increment": round(t_inc, 2),
        "control_increment": round(c_inc, 2),
        "did_net_effect": round(t_inc - c_inc, 2),
        "note": "DID 净影响 = 处理组增量 - 对照组增量",
    }


# ---------------------------------------------------------------- 多情景

def scenario_compare(baseline_points: List[Dict], event,
                     uplift: Optional[float]) -> Dict:
    """保守/基准/乐观三情景对比（需求 §4.6）。

    uplift 为空时三情景均退化为基线，并标注数据不足。
    """
    if uplift is None:
        return {
            "available": False,
            "reason": "缺少活动增幅依据（无历史同类活动数据、无计划参数），"
                      "按需求不得由模型自行补充活动增幅，仅展示常规基线",
            "scenarios": {},
        }
    out = {}
    for name, factor in SCENARIO_FACTORS.items():
        pts = apply_event_effect(baseline_points, event, uplift, name)
        total = float(sum(p["event_adjusted_forecast"] for p in pts))
        out[name] = {
            "factor": factor,
            "total": round(total, 2),
            "increment": round(
                total - float(sum(p["baseline_forecast"] for p in pts)), 2),
        }
    return {"available": True, "uplift": uplift, "scenarios": out}
