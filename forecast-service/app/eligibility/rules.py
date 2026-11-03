"""预测准入规则配置（不硬编码阈值，全部可配置）。

对应需求 §5.4 自动过滤规则与 §5.5 评分维度。
阈值集中于此，最终应根据真实数据分布校准。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class EligibilityRules:
    """准入规则配置。"""
    # 观察窗口（天）
    lookback_days: int = 56

    # ---- 历史覆盖 ----
    min_history_days_full: int = 28   # >= 此值视为历史充分
    min_history_days_min: int = 14    # < 此值视为历史不足

    # ---- 数据质量 ----
    min_completeness: float = 0.95    # 有效数据完整率下限

    # ---- 流量阈值 ----
    min_total_requests_eligible: int = 500   # 进入进一步评估的请求量下限
    min_active_days_eligible: int = 20       # 进入进一步评估的活跃天数下限
    cold_total_requests: int = 100           # 冷系统请求量上限
    cold_active_days: int = 5                # 冷系统活跃天数上限
    probation_total_requests: int = 500      # probation 请求量上限
    probation_active_days: int = 20          # probation 活跃天数上限

    # ---- 周期性检测 ----
    # 自相关阈值：高于此值认为存在稳定周期规律
    seasonality_acf_threshold: float = 0.3
    # 批处理接口的非零窗口集中度阈值（夜间集中度）
    batch_concentration_threshold: float = 0.6

    # ---- 资格评分权重（需求 §5.5）----
    score_weights: Dict[str, float] = field(default_factory=lambda: {
        "completeness": 0.20,     # 数据完整性
        "history_coverage": 0.15,  # 历史覆盖时间
        "volume": 0.20,           # 交易量充足程度
        "active_days": 0.15,      # 活跃天数
        "seasonality": 0.15,      # 时间周期规律
        "stability": 0.15,        # 交易量稳定性
    })

    # ---- 预测资格分档 ----
    predictability_bands: List[tuple] = field(default_factory=lambda: [
        (80, "high"),
        (60, "medium"),
        (40, "low"),
        (0, "none"),
    ])

    def band_for_score(self, score: float) -> str:
        for lo, label in self.predictability_bands:
            if score >= lo:
                return label
        return "none"


# 全局默认规则实例（可通过 API 覆盖）
default_rules = EligibilityRules()


def rules_to_dict(r: EligibilityRules) -> dict:
    return {
        "lookback_days": r.lookback_days,
        "min_history_days_full": r.min_history_days_full,
        "min_history_days_min": r.min_history_days_min,
        "min_completeness": r.min_completeness,
        "min_total_requests_eligible": r.min_total_requests_eligible,
        "min_active_days_eligible": r.min_active_days_eligible,
        "cold_total_requests": r.cold_total_requests,
        "cold_active_days": r.cold_active_days,
        "probation_total_requests": r.probation_total_requests,
        "probation_active_days": r.probation_active_days,
        "seasonality_acf_threshold": r.seasonality_acf_threshold,
        "batch_concentration_threshold": r.batch_concentration_threshold,
        "score_weights": r.score_weights,
        "predictability_bands": [
            {"min": lo, "label": lab} for lo, lab in r.predictability_bands
        ],
    }
