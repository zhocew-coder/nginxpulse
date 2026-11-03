"""活动日历 / 业务事件管理模块（需求 §4.2）。

对外暴露：
- BusinessEvent：活动数据模型
- event_phase_at：活动阶段判定（预热/正式/回落/不受影响）
- validate_event：活动参数校验（中文错误提示）
- resolve_phase_uplift：阶段增幅解析（增幅为空时返回 None，绝不编造）
"""
from .models import (
    BusinessEvent,
    CONFIDENCE_LEVELS,
    EVENT_STATUSES,
    EVENT_TYPES,
    IMPACT_LEVELS,
    PHASES,
    PHASE_UPLIFT_RATIO,
    active_events_at,
    event_phase_at,
    make_event_id,
    resolve_phase_uplift,
    validate_event,
)
from .mock_init import build_full_mock_events
from .adapter import load_events, to_business_event

__all__ = [
    "BusinessEvent",
    "CONFIDENCE_LEVELS",
    "EVENT_STATUSES",
    "EVENT_TYPES",
    "IMPACT_LEVELS",
    "PHASES",
    "PHASE_UPLIFT_RATIO",
    "active_events_at",
    "event_phase_at",
    "make_event_id",
    "resolve_phase_uplift",
    "validate_event",
    "build_full_mock_events",
    "load_events",
    "to_business_event",
]
