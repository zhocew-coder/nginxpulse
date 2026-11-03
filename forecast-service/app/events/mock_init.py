"""Mock 活动数据初始化（需求 §4.2，阶段四）。

复用 ``app.mock.generator.build_mock_events()``（双十一营销 / 月末批量清算 /
消费信贷推广），补齐完整活动模型字段（负责人、置信度、数据来源、状态等）。

注意：
- 不修改 generator.py，仅在其输出之上做字段补全。
- expected_uplift 严格沿用原始标注：原始为空的保持为空（不得编造增幅），
  置信度相应置为 low。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Optional

from ..core.config import settings
from ..mock.generator import TZ, build_mock_events
from .models import BusinessEvent, normalize_event


# 各 mock 活动的补充元信息（key = MockEvent.event_id）
_MOCK_EVENT_META: Dict[str, Dict[str, object]] = {
    "evt_2026_s11": {
        "business_type": "支付营销",
        "event_owner": "零售支付运营组",
        "target_uris": ["/api/transaction/submit", "/api/transfer/confirm"],
        "historical_event_id": "evt_2025_s11",
        # 原始 mock 未标注增幅：保持为空，置信度置 low（不编造）
        "expected_uplift": None,
        "confidence": "low",
    },
    "evt_monthly_batch": {
        "business_type": "清算批处理",
        "event_owner": "数据中心运维组",
        "target_uris": ["/api/batch/clearing"],
        "historical_event_id": None,
        "expected_uplift": None,
        "confidence": "low",
    },
    "evt_loan_promo": {
        "business_type": "消费信贷",
        "event_owner": "零售信贷部",
        "target_uris": [],
        "historical_event_id": None,
        # 历史同类活动实测增幅，标注后可用于活动影响推算
        "expected_uplift": 1.4,
        "confidence": "medium",
    },
}


def build_full_mock_events(history_days: Optional[int] = None) -> List[BusinessEvent]:
    """构造完整的 mock 活动列表（字段齐全，可直接落库）。

    Args:
        history_days: mock 历史覆盖天数，缺省取配置 ``mock_history_days``

    Returns:
        归一化后的 BusinessEvent 列表（至少 3 个活动）
    """
    days = history_days if history_days is not None else settings.mock_history_days
    end = datetime.now(TZ).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=days)
    now = datetime.now(TZ)

    events: List[BusinessEvent] = []
    for raw in build_mock_events(start, end):
        meta = _MOCK_EVENT_META.get(raw.event_id, {})
        status = raw.status or "confirmed"
        # 结束时间仍在未来的活动不应是"已完成"
        if raw.end and raw.end > now and status == "completed":
            status = "confirmed"
        ev = BusinessEvent(
            event_id=raw.event_id,
            event_name=raw.event_name,
            event_type=raw.event_type if raw.event_type in
            ("marketing", "batch", "promotion", "launch", "holiday") else "marketing",
            start_time=raw.start,
            end_time=raw.end,
            preheat_start=raw.preheat_start,
            preheat_end=raw.start if raw.preheat_start else None,
            cooldown_end=raw.cooldown_end,
            target_apps=list(raw.target_apps or []),
            target_uris=list(meta.get("target_uris") or []),
            business_type=str(meta.get("business_type", "")),
            impact_level=raw.impact_level or "medium",
            expected_uplift=meta.get("expected_uplift", raw.expected_uplift),
            historical_event_id=meta.get("historical_event_id", None),
            event_owner=str(meta.get("event_owner", "mock")),
            data_source="mock",
            confidence=str(meta.get("confidence", "low")),
            status=status,
        )
        events.append(normalize_event(ev))
    return events
