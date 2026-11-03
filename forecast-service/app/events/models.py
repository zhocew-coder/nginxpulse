"""活动（业务事件）数据模型与阶段计算（需求 §4.2 / §4.3）。

设计原则（需求核心约束）：
- ``expected_uplift``（预期增幅）允许为空。为空时**不得编造活动增幅**，
  任何需要增幅的计算都必须显式返回 None / 低置信度，而不是填默认值。
- 活动影响按四阶段拆分：预热（preheat）/ 正式（active）/ 收尾（正式期末尾）
  / 回落（cooldown）。本模块负责阶段判定，增幅拆分由活动影响算法负责。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Tuple, Union

# 项目统一使用东八区（与 mock 生成器保持一致）
TZ = timezone(timedelta(hours=8))

# 活动类型：营销 / 批量 / 推广 / 上线 / 节假日
EVENT_TYPES: Tuple[str, ...] = ("marketing", "batch", "promotion", "launch", "holiday")
# 影响等级
IMPACT_LEVELS: Tuple[str, ...] = ("low", "medium", "high")
# 活动状态：草稿 / 已确认 / 已完成 / 已取消
EVENT_STATUSES: Tuple[str, ...] = ("draft", "confirmed", "completed", "cancelled")
# 置信度（增幅未标注时一律 low）
CONFIDENCE_LEVELS: Tuple[str, ...] = ("high", "medium", "low")
# 活动阶段
PHASES: Tuple[str, ...] = ("preheat", "active", "cooldown", "none")

# 各阶段相对"正式期增幅"的经验折算比例。
# 注意：仅当 expected_uplift 已明确标注时才允许使用该比例；
# expected_uplift 为空时不得据此推算增幅。
PHASE_UPLIFT_RATIO: Dict[str, float] = {
    "preheat": 0.5,
    "active": 1.0,
    "cooldown": 0.3,
    "none": 0.0,
}

# 活动类型 / 状态 / 影响等级的中文说明，便于前端展示与错误提示
EVENT_TYPE_LABELS: Dict[str, str] = {
    "marketing": "营销活动",
    "batch": "批量作业",
    "promotion": "业务推广",
    "launch": "新功能上线",
    "holiday": "节假日",
}
IMPACT_LEVEL_LABELS: Dict[str, str] = {"low": "低", "medium": "中", "high": "高"}
EVENT_STATUS_LABELS: Dict[str, str] = {
    "draft": "草稿",
    "confirmed": "已确认",
    "completed": "已完成",
    "cancelled": "已取消",
}
PHASE_LABELS: Dict[str, str] = {
    "preheat": "预热期",
    "active": "正式期",
    "cooldown": "回落期",
    "none": "不受影响",
}


def make_event_id(prefix: str = "evt") -> str:
    """生成活动 ID（调用方未指定 event_id 时使用）。"""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _ensure_dt(value: Union[datetime, str, None]) -> Optional[datetime]:
    """把入参统一转成带时区的 datetime。

    - datetime：无时区时按东八区处理（银行数据中心口径）
    - str：按 ISO-8601 解析，无时区时按东八区处理
    - None / 空串：原样返回 None
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=TZ)
    text = str(value).strip()
    if not text:
        return None
    # 兼容 "...Z" 结尾的 UTC 表示
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=TZ)


def _to_tz(dt: Optional[datetime]) -> Optional[datetime]:
    """把带时区的时间统一转成东八区表示（None 原样返回）。"""
    return dt.astimezone(TZ) if dt is not None else None


@dataclass
class BusinessEvent:
    """业务活动 / 重大事件。

    字段含义：
    - event_id：活动唯一标识
    - event_name：活动名称
    - event_type：marketing / batch / promotion / launch / holiday
    - start_time / end_time：正式期起止（必填，且 start_time < end_time）
    - preheat_start / preheat_end：预热期起止（可为空）
    - cooldown_end：回落期结束时间（可为空）
    - target_apps：受影响应用列表（必填，至少一个）
    - target_uris：受影响 URL 模板列表（为空表示应用下全部 URL）
    - business_type：业务类型（如"支付营销""清算批处理"）
    - impact_level：low / medium / high
    - expected_uplift：预期增幅（如 1.8 表示 +180%），**允许为空**
    - historical_event_id：可参考的历史同期活动 ID
    - event_owner：活动负责人 / 归属团队
    - data_source：数据来源（mock / manual / external）
    - confidence：high / medium / low（增幅为空时强制 low）
    - status：draft / confirmed / completed / cancelled
    """

    event_id: str
    event_name: str
    start_time: datetime
    end_time: datetime
    event_type: str = "marketing"
    preheat_start: Optional[datetime] = None
    preheat_end: Optional[datetime] = None
    cooldown_end: Optional[datetime] = None
    target_apps: List[str] = field(default_factory=list)
    target_uris: List[str] = field(default_factory=list)
    business_type: str = ""
    impact_level: str = "medium"
    expected_uplift: Optional[float] = None
    historical_event_id: Optional[str] = None
    event_owner: str = ""
    data_source: str = "manual"
    confidence: str = "low"
    status: str = "draft"

    # ---------------------------------------------------------------- 归一化

    def __post_init__(self) -> None:
        """归一化时间字段与列表字段，保证后续比较安全。

        所有时间统一转成东八区表示：入参可以是 +08:00、+00:00 或 Z 结尾，
        输出必须是同一种表示，避免前端按字符串解析时出现 8 小时偏差。
        """
        self.start_time = _to_tz(_ensure_dt(self.start_time) or datetime.now(TZ))
        self.end_time = _to_tz(_ensure_dt(self.end_time) or self.start_time)
        self.preheat_start = _to_tz(_ensure_dt(self.preheat_start))
        self.preheat_end = _to_tz(_ensure_dt(self.preheat_end))
        self.cooldown_end = _to_tz(_ensure_dt(self.cooldown_end))
        self.target_apps = [str(a) for a in (self.target_apps or [])]
        self.target_uris = [str(u) for u in (self.target_uris or [])]
        if self.event_type not in EVENT_TYPES:
            self.event_type = self.event_type or "marketing"
        if self.confidence not in CONFIDENCE_LEVELS:
            self.confidence = "low"
        # 核心约束：未标注预期增幅时，置信度不得为 high/medium
        if self.expected_uplift is None and self.confidence != "low":
            self.confidence = "low"

    # ---------------------------------------------------------------- 序列化

    def to_dict(self) -> Dict[str, object]:
        """转成可落库 / 可 JSON 序列化的字典（时间为 ISO 字符串）。"""
        return {
            "event_id": self.event_id,
            "event_name": self.event_name,
            "event_type": self.event_type,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "preheat_start": self.preheat_start.isoformat() if self.preheat_start else None,
            "preheat_end": self.preheat_end.isoformat() if self.preheat_end else None,
            "cooldown_end": self.cooldown_end.isoformat() if self.cooldown_end else None,
            "target_apps": list(self.target_apps),
            "target_uris": list(self.target_uris),
            "business_type": self.business_type,
            "impact_level": self.impact_level,
            "expected_uplift": self.expected_uplift,
            "historical_event_id": self.historical_event_id,
            "event_owner": self.event_owner,
            "data_source": self.data_source,
            "confidence": self.confidence,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "BusinessEvent":
        """从字典（DB 行 / API 入参 / mock）构造活动。缺省字段走默认值。"""
        return cls(
            event_id=str(data.get("event_id") or ""),
            event_name=str(data.get("event_name") or ""),
            start_time=_ensure_dt(data.get("start_time")) or datetime.now(TZ),
            end_time=_ensure_dt(data.get("end_time")) or datetime.now(TZ),
            event_type=str(data.get("event_type") or "marketing"),
            preheat_start=_ensure_dt(data.get("preheat_start")),
            preheat_end=_ensure_dt(data.get("preheat_end")),
            cooldown_end=_ensure_dt(data.get("cooldown_end")),
            target_apps=list(data.get("target_apps") or []),
            target_uris=list(data.get("target_uris") or []),
            business_type=str(data.get("business_type") or ""),
            impact_level=str(data.get("impact_level") or "medium"),
            expected_uplift=data.get("expected_uplift", None),
            historical_event_id=data.get("historical_event_id", None),
            event_owner=str(data.get("event_owner") or ""),
            data_source=str(data.get("data_source") or "manual"),
            confidence=str(data.get("confidence") or "low"),
            status=str(data.get("status") or "draft"),
        )

    # ---------------------------------------------------------------- 阶段

    def preheat_window(self) -> Tuple[Optional[datetime], Optional[datetime]]:
        """返回预热期窗口 (起, 止)。

        仅配置 preheat_start 时，预热期止点默认为正式期开始时间
        （需求 §4.2 的 preheat_end 允许为空，此处做等价补全，不编造增幅）。
        """
        start = self.preheat_start
        if start is None:
            return (None, None)
        end = self.preheat_end or self.start_time
        return (start, end)

    def phase_at(self, ts: Union[datetime, str, None] = None) -> str:
        """判断给定时间点处于活动的哪个阶段（``phase_of`` 的兼容别名）。"""
        return self.phase_of(ts)

    def phase_of(self, ts: Union[datetime, str, None] = None) -> str:
        """返回给定时间点 ts 所处的阶段 —— **阶段判定唯一入口**。

        阶段语义（需求 §4.3，优先级：正式期 > 回落期 > 预热期 > 不受影响）：
        - ``preheat``  预热期：preheat_start <= ts < preheat_end（默认止点为 start_time）
        - ``active``   正式期：start_time <= ts <= end_time（含起止端点）
        - ``cooldown`` 回落期：end_time < ts <= cooldown_end（含止点）
        - ``none``     不受影响：其余时间（含活动未配置对应阶段的情况）

        Args:
            ts: 时间点（datetime / ISO 字符串），缺省为当前时间

        Returns:
            preheat / active / cooldown / none
        """
        point = _ensure_dt(ts) if ts is not None else datetime.now(TZ)

        # 正式期（含起止端点）
        if self.start_time <= point <= self.end_time:
            return "active"

        # 回落期：正式期结束之后到 cooldown_end
        if self.cooldown_end is not None and self.end_time < point <= self.cooldown_end:
            return "cooldown"

        # 预热期：正式期开始之前
        pre_start, pre_end = self.preheat_window()
        if pre_start is not None and pre_end is not None and pre_start <= point < pre_end:
            return "preheat"

        return "none"

    def current_phase(self, dt: Union[datetime, str, None] = None) -> str:
        """返回当前时间（或指定时间 dt）所处的阶段。

        与 ``phase_of`` 等价，语义化入口：不传 dt 即"当前"。
        """
        return self.phase_of(dt)

    def phase_progress(self, ts: Union[datetime, str, None],
                       phase: Optional[str] = None) -> float:
        """返回 ts 在指定阶段内的进度，取值 [0.0, 1.0]。

        进度口径（供活动影响算法做阶段内渐变/衰减，判定逻辑与 ``phase_of`` 同源）：
        - ``preheat``  ：preheat_start -> start_time 之间线性递增 0 -> 1
        - ``active``   ：恒为 1.0（正式期满额）
        - ``cooldown`` ：end_time -> cooldown_end 之间线性递增 0 -> 1
        - ``none``     ：恒为 0.0

        Args:
            ts: 时间点，缺省为当前时间
            phase: 指定阶段；缺省时取 ts 时刻的阶段（``phase_of``）

        Returns:
            阶段内进度 [0.0, 1.0]；所需窗口缺失时返回 0.0
        """
        point = _ensure_dt(ts) if ts is not None else datetime.now(TZ)
        target = phase or self.phase_of(point)
        if target == "active":
            return 1.0
        if target == "preheat":
            if self.preheat_start is None:
                return 0.0
            span = (self.start_time - self.preheat_start).total_seconds()
            if span <= 0:
                return 0.0
            prog = (point - self.preheat_start).total_seconds() / span
            return float(min(max(prog, 0.0), 1.0))
        if target == "cooldown":
            if self.cooldown_end is None:
                return 0.0
            span = (self.cooldown_end - self.end_time).total_seconds()
            if span <= 0:
                return 0.0
            prog = (point - self.end_time).total_seconds() / span
            return float(min(max(prog, 0.0), 1.0))
        return 0.0

    def covers(self, app_name: str, uri_template: str = "") -> bool:
        """判断活动是否覆盖指定应用 / URL。

        target_uris 为空表示覆盖该应用下的全部 URL。
        """
        if self.target_apps and app_name not in self.target_apps:
            return False
        if self.target_uris and uri_template and uri_template not in self.target_uris:
            return False
        return True


# ---------------------------------------------------------------- 阶段计算

def event_phase_at(event: Union[BusinessEvent, Dict[str, object]],
                   ts: Union[datetime, str, None] = None) -> str:
    """判断给定时间点 ts 时活动所处的阶段（需求 §4.3）。

    **模块级便捷入口，判定逻辑统一委托 ``BusinessEvent.phase_of``**，
    本函数只做入参归一化（dict -> BusinessEvent），消除重复实现。

    返回：preheat / active / cooldown / none（语义见 ``BusinessEvent.phase_of``）。
    """
    ev = event if isinstance(event, BusinessEvent) else BusinessEvent.from_dict(event)
    return ev.phase_of(ts)


def resolve_phase_uplift(event: Union[BusinessEvent, Dict[str, object]],
                         phase: str,
                         ts: Union[datetime, str, None] = None
                         ) -> Tuple[Optional[float], str]:
    """解析某阶段的可用增幅（需求核心约束：为空时绝不编造）。

    返回 ``(uplift, note)``：
    - 活动未标注 ``expected_uplift`` 时返回 ``(None, "未标注预期增幅，不做编造")``，
      调用方必须按"数据不足 / 低置信度"处理。
    - 已标注时，按阶段经验比例折算：预热 50%、正式 100%、回落 30% 并按回落进度衰减。

    Args:
        event: 活动对象或活动字典
        phase: preheat / active / cooldown / none
        ts: 回落期衰减计算所需的时间点，缺省为当前时间

    Returns:
        (增幅或 None, 说明文案)
    """
    ev = event if isinstance(event, BusinessEvent) else BusinessEvent.from_dict(event)
    if ev.expected_uplift is None:
        return (None, "未标注预期增幅（expected_uplift 为空），不做编造，按数据不足处理")
    if phase not in PHASE_UPLIFT_RATIO:
        return (None, f"未知阶段：{phase}")

    ratio = PHASE_UPLIFT_RATIO[phase]
    if phase == "cooldown":
        # 回落进度与阶段判定同源（BusinessEvent.phase_progress），随进度平方衰减
        point = _ensure_dt(ts) if ts is not None else datetime.now(TZ)
        progress = ev.phase_progress(point, "cooldown")
        ratio = ratio * (1.0 - progress) ** 2
    return (float(ev.expected_uplift) * ratio, f"按{PHASE_LABELS.get(phase, phase)}经验比例折算")


def active_events_at(events: Sequence[Union[BusinessEvent, Dict[str, object]]],
                     ts: Union[datetime, str, None] = None,
                     app_name: Optional[str] = None,
                     uri_template: str = "") -> List[Dict[str, object]]:
    """查询某时间点生效（阶段 != none）的活动，供活动影响算法使用。

    Args:
        events: 活动列表（BusinessEvent 或字典）
        ts: 时间点，缺省为当前时间
        app_name: 指定应用时只返回覆盖该应用的活动
        uri_template: 指定 URL 时只返回覆盖该 URL 的活动

    Returns:
        [{"event": 活动字典, "phase": 阶段, "uplift": 增幅或 None, "note": 说明}]
    """
    point = _ensure_dt(ts) if ts is not None else datetime.now(TZ)
    out: List[Dict[str, object]] = []
    for raw in events:
        ev = raw if isinstance(raw, BusinessEvent) else BusinessEvent.from_dict(raw)
        if ev.status == "cancelled":
            continue  # 已取消活动不参与影响计算
        phase = event_phase_at(ev, point)
        if phase == "none":
            continue
        if app_name is not None and not ev.covers(app_name, uri_template):
            continue
        uplift, note = resolve_phase_uplift(ev, phase, point)
        out.append({
            "event": ev.to_dict(),
            "phase": phase,
            "uplift": uplift,
            "note": note,
        })
    return out


# ---------------------------------------------------------------- 校验

def validate_event(event: Union[BusinessEvent, Dict[str, object]]) -> List[str]:
    """校验活动参数，返回中文错误列表（空列表表示校验通过）。

    校验项：
    - event_id / event_name 非空
    - event_type / impact_level / status / confidence 取值合法
    - start_time < end_time
    - target_apps 非空
    - 预热期、回落期与正式期的时间顺序合理
    - expected_uplift 若填写需为有限数值且 > -1（不允许完全抵消为负）
    """
    ev = event if isinstance(event, BusinessEvent) else BusinessEvent.from_dict(event)
    errors: List[str] = []

    if not ev.event_id.strip():
        errors.append("活动 ID（event_id）不能为空")
    if not ev.event_name.strip():
        errors.append("活动名称（event_name）不能为空")
    if ev.event_type not in EVENT_TYPES:
        errors.append(f"活动类型（event_type）非法：{ev.event_type}，可选值：{','.join(EVENT_TYPES)}")
    if ev.impact_level not in IMPACT_LEVELS:
        errors.append(f"影响等级（impact_level）非法：{ev.impact_level}，可选值：{','.join(IMPACT_LEVELS)}")
    if ev.status not in EVENT_STATUSES:
        errors.append(f"活动状态（status）非法：{ev.status}，可选值：{','.join(EVENT_STATUSES)}")
    if ev.confidence not in CONFIDENCE_LEVELS:
        errors.append(f"置信度（confidence）非法：{ev.confidence}，可选值：{','.join(CONFIDENCE_LEVELS)}")

    if ev.start_time >= ev.end_time:
        errors.append("活动时间不合法：start_time 必须早于 end_time")

    if not ev.target_apps:
        errors.append("受影响应用（target_apps）不能为空，至少需指定一个应用")

    pre_start, pre_end = ev.preheat_window()
    if pre_start is not None:
        if pre_end is not None and pre_start >= pre_end:
            errors.append("预热期时间不合法：preheat_start 必须早于 preheat_end")
        if pre_start >= ev.start_time:
            errors.append("预热期时间不合法：preheat_start 必须早于 start_time")
        if pre_end is not None and pre_end > ev.start_time:
            errors.append("预热期时间不合法：preheat_end 不能晚于 start_time")
    if ev.cooldown_end is not None and ev.cooldown_end < ev.end_time:
        errors.append("回落期时间不合法：cooldown_end 不能早于 end_time")

    if ev.expected_uplift is not None:
        try:
            uplift = float(ev.expected_uplift)
        except (TypeError, ValueError):
            errors.append("预期增幅（expected_uplift）必须是数值")
        else:
            if uplift != uplift:  # NaN
                errors.append("预期增幅（expected_uplift）不能为 NaN")
            elif uplift <= -1.0:
                errors.append("预期增幅（expected_uplift）必须大于 -1（-1 表示流量归零）")

    return errors


def normalize_event(event: Union[BusinessEvent, Dict[str, object]]) -> BusinessEvent:
    """归一化活动：补全预热期止点、回落期缺省值与置信度。

    - 只配置了 preheat_start 时，preheat_end 默认取 start_time
    - 未配置 cooldown_end 时默认取 end_time（即无回落期）
    - expected_uplift 为空时置信度强制为 low（核心约束）
    """
    ev = event if isinstance(event, BusinessEvent) else BusinessEvent.from_dict(event)
    pre_start, pre_end = ev.preheat_window()
    if pre_start is not None and ev.preheat_end is None:
        ev.preheat_end = pre_end
    if ev.cooldown_end is None:
        ev.cooldown_end = ev.end_time
    if ev.expected_uplift is None:
        ev.confidence = "low"
    return ev
