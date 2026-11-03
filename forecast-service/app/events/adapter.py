"""活动数据适配层（阶段四：活动影响分析的数据源统一）。

职责：把不同来源的活动对象统一成 ``app.events.models.BusinessEvent``：

- ``event_store`` 的行字典（PG / 内存双模式，字段为 start_time/end_time + ISO 字符串）
- ``MockEvent``（``app/mock/generator.py``，字段为 start/end）
- 已经是 ``BusinessEvent`` 的对象（原样返回）

供 ``app/forecast/event_impact.py`` 使用：

- ``load_events()``：影响分析的事件来源（缺口2：用户创建的活动进入影响分析）
- ``to_business_event()``：字段名兼容转换（缺口1：阶段判定统一走 events/models.py）

设计约束：
- 本层只做"取数 + 字段适配"，不做任何增幅/阶段算法（算法在 event_impact 与 models 中）。
- 真实模式（USE_MOCK=false）绝不回退 mock 活动，避免把虚构活动带入增幅估计。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..core.config import settings
from .models import BusinessEvent


# MockEvent（start/end）到 BusinessEvent（start_time/end_time）的字段别名
_FIELD_ALIASES = {
    "start_time": ("start_time", "start"),
    "end_time": ("end_time", "end"),
}


def to_business_event(raw: Any) -> BusinessEvent:
    """把任意形态的活动对象转换成 BusinessEvent。

    支持：
    - BusinessEvent 实例（原样返回）
    - dict：event_store 行（start_time/end_time）或 MockEvent 字典（start/end）
    - 任意带属性的对象（MockEvent 实例等）

    Raises:
        ValueError: 缺少活动时间（既无 start_time 也无 start）
    """
    if isinstance(raw, BusinessEvent):
        return raw

    if isinstance(raw, dict):
        data: Dict[str, Any] = dict(raw)
    else:
        data = {
            "event_id": getattr(raw, "event_id", ""),
            "event_name": getattr(raw, "event_name", ""),
            "event_type": getattr(raw, "event_type", "marketing"),
            # MockEvent 用 start/end，BusinessEvent 用 start_time/end_time
            "start_time": getattr(raw, "start_time", None) or getattr(raw, "start", None),
            "end_time": getattr(raw, "end_time", None) or getattr(raw, "end", None),
            "preheat_start": getattr(raw, "preheat_start", None),
            "preheat_end": getattr(raw, "preheat_end", None),
            "cooldown_end": getattr(raw, "cooldown_end", None),
            "target_apps": list(getattr(raw, "target_apps", []) or []),
            "target_uris": list(getattr(raw, "target_uris", []) or []),
            "business_type": getattr(raw, "business_type", ""),
            "impact_level": getattr(raw, "impact_level", "medium"),
            "expected_uplift": getattr(raw, "expected_uplift", None),
            "historical_event_id": getattr(raw, "historical_event_id", None),
            "event_owner": getattr(raw, "event_owner", ""),
            "data_source": getattr(raw, "data_source", "manual"),
            "confidence": getattr(raw, "confidence", "low"),
            "status": getattr(raw, "status", "draft"),
        }

    # 字段名兼容：MockEvent 的 start/end -> start_time/end_time
    for canonical, aliases in _FIELD_ALIASES.items():
        if data.get(canonical) in (None, ""):
            for alias in aliases:
                if alias != canonical and data.get(alias) not in (None, ""):
                    data[canonical] = data[alias]
                    break

    if data.get("start_time") in (None, ""):
        raise ValueError(
            f"活动缺少开始时间（start_time/start）：{data.get('event_id') or data.get('event_name')}"
        )
    return BusinessEvent.from_dict(data)


def load_events(status: Optional[str] = None,
                include_cancelled: bool = False,
                limit: int = 1000) -> List[BusinessEvent]:
    """加载活动列表，作为影响分析（历史同类活动查找）的事件来源。

    顺序：
    1. 优先读 ``event_store``（PG 可用时读库，否则读内存）——
       这样用户通过 API 创建的活动也能进入影响分析（缺口2）。
    2. 库为空且 USE_MOCK=true 时回退 mock 活动，保证开发/联调链路可用；
       真实模式（USE_MOCK=false）绝不回退，避免虚构活动污染增幅估计。

    Args:
        status: 按活动状态筛选（None 表示不限）
        include_cancelled: 是否包含已取消的活动（默认排除，取消的活动不产生影响）
        limit: 最多返回条数

    Returns:
        BusinessEvent 列表
    """
    from ..storage import event_store

    rows = event_store.list_events(status=status, limit=limit)
    events: List[BusinessEvent] = []
    for row in rows:
        try:
            ev = to_business_event(row)
        except Exception as e:
            # 单条脏数据不应中断整条影响分析链路
            print(f"[adapter] 跳过非法活动记录 "
                  f"{row.get('event_id') if isinstance(row, dict) else '?'}: {e}")
            continue
        if ev.status == "cancelled" and not include_cancelled:
            continue
        events.append(ev)

    if not events and settings.use_mock:
        from .mock_init import build_full_mock_events
        events = [e for e in build_full_mock_events()
                  if include_cancelled or e.status != "cancelled"]
    return events
