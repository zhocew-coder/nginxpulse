"""阶段四活动日历 / 业务事件模块测试（真实 HTTP 调用 + 直接函数验证）。

覆盖：
1. 初始化 mock 活动（≥3 个）
2. 创建活动（含参数校验失败场景）
3. 查询列表 / 按应用筛选 / 按状态筛选
4. 查询单个活动
5. 阶段计算：预热 / 正式 / 回落 / 不受影响 各验证一个时间点
6. 未标注增幅时不得编造（uplift=None + 低置信度）
7. 删除活动

用法：
    FORECAST_TEST_PORT=8090 python tests/test_events.py
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

# 允许直接以脚本方式运行：把项目根目录加入 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.events.models import (  # noqa: E402
    BusinessEvent,
    TZ,
    event_phase_at,
    resolve_phase_uplift,
    validate_event,
)

PORT = os.getenv("FORECAST_TEST_PORT", "8090")
BASE = f"http://127.0.0.1:{PORT}/api/forecast/v1"

PASS, FAIL = 0, 0


def check(name: str, ok: bool, extra: str = "") -> None:
    """统一的断言输出。"""
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name} {extra}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {extra}")


def post(path, payload):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"_http_error": e.code,
                "detail": json.loads(e.read().decode("utf-8")).get("detail")}


def get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=120) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"_http_error": e.code,
                "detail": json.loads(e.read().decode("utf-8")).get("detail")}


def delete(path):
    req = urllib.request.Request(BASE + path, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"_http_error": e.code,
                "detail": json.loads(e.read().decode("utf-8")).get("detail")}


# ============================================================ 1. 初始化 mock
print("1. 初始化 mock 活动：")
r = post("/events/init-mock", {})
if "_http_error" in r:
    check("init-mock", False, f"HTTP {r['_http_error']} {r['detail']}")
    print("服务不可用，后续测试中止")
    sys.exit(1)
check("init-mock 返回成功", r.get("ok") is True, f"count={r.get('count')}")
check("mock 活动数量 >= 3", r.get("count", 0) >= 3,
      f"活动={[e['event_id'] for e in r.get('events', [])]}")
for e in r.get("events", []):
    print(f"     - {e['event_id']} | {e['event_name']} | 类型={e['event_type']} "
          f"| 状态={e['status']} | 增幅={e['expected_uplift']} | 置信度={e['confidence']} "
          f"| 应用={e['target_apps']}")

# ============================================================ 2. 创建活动
print("2. 创建活动（含预热期与回落期，未标注增幅）：")
now = datetime.now(TZ).replace(minute=0, second=0, microsecond=0)
payload = {
    "event_name": "测试用例-新年营销活动",
    "event_type": "marketing",
    "start_time": (now + timedelta(days=5)).isoformat(),
    "end_time": (now + timedelta(days=7)).isoformat(),
    "preheat_start": (now + timedelta(days=3)).isoformat(),
    "preheat_end": (now + timedelta(days=5)).isoformat(),
    "cooldown_end": (now + timedelta(days=9)).isoformat(),
    "target_apps": ["core-payment", "core-card"],
    "target_uris": ["/api/transaction/submit"],
    "business_type": "支付营销",
    "impact_level": "high",
    "expected_uplift": None,      # 未标注：不得编造
    "event_owner": "测试工程师",
    "status": "confirmed",
}
r = post("/events", payload)
check("创建活动成功", r.get("ok") is True, f"message={r.get('message')}")
event_id = (r.get("event") or {}).get("event_id", "")
created = r.get("event") or {}
check("返回活动含 event_id", bool(event_id), f"event_id={event_id}")
check("未标注增幅时置信度为 low", created.get("confidence") == "low",
      f"confidence={created.get('confidence')}")
check("未标注增幅时 expected_uplift 为 None", created.get("expected_uplift") is None,
      f"expected_uplift={created.get('expected_uplift')}")

# 2.1 参数校验：start_time >= end_time
print("2.1 参数校验（start_time >= end_time 应报错 400）：")
bad = dict(payload, start_time=(now + timedelta(days=7)).isoformat(),
           end_time=(now + timedelta(days=5)).isoformat())
r_bad = post("/events", bad)
check("时间倒序被拒绝", r_bad.get("_http_error") == 400,
      f"detail={r_bad.get('detail')}")

# 2.2 参数校验：target_apps 为空
print("2.2 参数校验（target_apps 为空应报错 400）：")
bad2 = dict(payload, target_apps=[])
r_bad2 = post("/events", bad2)
check("空 target_apps 被拒绝", r_bad2.get("_http_error") == 400,
      f"detail={r_bad2.get('detail')}")

# ============================================================ 3. 查询列表
print("3. 查询活动列表：")
r = get("/events")
check("列表返回成功", "events" in r, f"total={r.get('total')} count={r.get('count')}")
check("列表包含新建活动", any(e["event_id"] == event_id for e in r.get("events", [])))

# 前端表格按 start_time 字符串排序，故所有时间必须统一后缀（东八区）
starts = [str(e.get("start_time", "")) for e in r.get("events", [])]
check("所有 start_time 统一 +08:00 后缀",
      all(s.endswith("+08:00") for s in starts), f"样例={starts[:2]}")
check("列表按 start_time 倒序（字典序==时间序）",
      starts == sorted(starts, reverse=True), f"顺序={starts}")

print("3.1 按应用筛选（app_name=std-loan）：")
r = get("/events?app_name=std-loan")
hits = r.get("events", [])
check("筛选结果非空", len(hits) > 0, f"命中 {len(hits)} 个：{[e['event_id'] for e in hits]}")
check("筛选结果均覆盖 std-loan",
      all("std-loan" in e["target_apps"] for e in hits))

print("3.2 按状态筛选（status=confirmed）：")
r = get("/events?status=confirmed")
hits = r.get("events", [])
check("状态筛选生效", all(e["status"] == "confirmed" for e in hits),
      f"命中 {len(hits)} 个")

print("3.3 按开始时间范围筛选：")
f_from = (now - timedelta(days=1)).isoformat()
f_to = (now + timedelta(days=30)).isoformat()
r = get(f"/events?start_from={urllib.parse.quote(f_from)}&start_to={urllib.parse.quote(f_to)}")
check("时间范围筛选返回成功", "events" in r, f"count={r.get('count')}")

# ============================================================ 4. 查询单个
print("4. 查询单个活动：")
r = get(f"/events/{event_id}")
check("单个查询成功", r.get("event_id") == event_id,
      f"名称={r.get('event_name')} 类型={r.get('event_type')}")
print(f"     预热 {r.get('preheat_start')} ~ {r.get('preheat_end')}")
print(f"     正式 {r.get('start_time')} ~ {r.get('end_time')}")
print(f"     回落 至 {r.get('cooldown_end')}")

r404 = get("/events/not_exist_event_xxx")
check("不存在的活动返回 404", r404.get("_http_error") == 404, f"detail={r404.get('detail')}")

# ============================================================ 5. 阶段计算
print("5. 阶段计算（预热 / 正式 / 回落 / 不受影响）：")
start_t = datetime.fromisoformat(r.get("start_time"))
end_t = datetime.fromisoformat(r.get("end_time"))
pre_t = datetime.fromisoformat(r.get("preheat_start"))
cool_end_t = datetime.fromisoformat(r.get("cooldown_end"))

# 5.1 直接调用模型函数
ev_obj = BusinessEvent.from_dict(r)
pre_point = pre_t + timedelta(hours=1)
active_point = start_t + timedelta(hours=1)
cool_point = end_t + timedelta(hours=1)
none_point = start_t - timedelta(days=10)

p_pre = event_phase_at(ev_obj, pre_point)
p_active = event_phase_at(ev_obj, active_point)
p_cool = event_phase_at(ev_obj, cool_point)
p_none = event_phase_at(ev_obj, none_point)
check("预热期判定", p_pre == "preheat", f"{pre_point.isoformat()} -> {p_pre}")
check("正式期判定", p_active == "active", f"{active_point.isoformat()} -> {p_active}")
check("回落期判定", p_cool == "cooldown", f"{cool_point.isoformat()} -> {p_cool}")
check("不受影响判定", p_none == "none", f"{none_point.isoformat()} -> {p_none}")
check("正式期端点仍为 active", event_phase_at(ev_obj, end_t) == "active",
      f"{end_t.isoformat()}")
check("回落期端点仍为 cooldown", event_phase_at(ev_obj, cool_end_t) == "cooldown",
      f"{cool_end_t.isoformat()}")

# 5.2 通过 API 验证同一时间点
for label, point, expect in [("预热", pre_point, "preheat"),
                             ("正式", active_point, "active"),
                             ("回落", cool_point, "cooldown"),
                             ("不受影响", none_point, "none")]:
    quoted = urllib.parse.quote(point.isoformat())
    pr = get(f"/events/{event_id}/phase?ts={quoted}")
    check(f"API 阶段-{label}", pr.get("phase") == expect,
          f"{point.isoformat()} -> {pr.get('phase')}（{pr.get('phase_label')}）"
          f" uplift={pr.get('uplift')} note={pr.get('note')}")

# ============================================================ 6. 不编造增幅
print("6. 未标注增幅时不得编造：")
u_none, note_none = resolve_phase_uplift(ev_obj, "active", active_point)
check("增幅为空时返回 None", u_none is None, f"note={note_none}")
check("置信度为 low", (get(f"/events/{event_id}") or {}).get("confidence") == "low")

print("6.1 已标注增幅时按阶段折算：")
ev_uplift = BusinessEvent.from_dict(dict(r, expected_uplift=1.0))
u_active, n1 = resolve_phase_uplift(ev_uplift, "active", active_point)
u_pre, n2 = resolve_phase_uplift(ev_uplift, "preheat", pre_point)
u_cool, n3 = resolve_phase_uplift(ev_uplift, "cooldown", cool_point)
check("正式期增幅 = 标注值", abs((u_active or 0) - 1.0) < 1e-9, f"uplift={u_active}")
check("预热期增幅 = 50%", abs((u_pre or 0) - 0.5) < 1e-9, f"uplift={u_pre}")
check("回落期增幅 < 正式期", (u_cool or 0) < (u_active or 0), f"uplift={u_cool} ({n3})")

# ============================================================ 6.4 时区表示一致
print("6.4 时间表示一致性（入参 Z / +08:00 都应统一为 +08:00）：")
utc_payload = {
    "event_name": "时区一致性检查-Z入参",
    "event_type": "promotion",
    "start_time": "2026-12-01T10:00:00Z",
    "end_time": "2026-12-02T10:00:00Z",
    "target_apps": ["core-payment"],
    "status": "draft",
}
r_utc = post("/events", utc_payload)
utc_id = (r_utc.get("event") or {}).get("event_id", "")
created_utc = r_utc.get("event") or {}
check("Z 入参创建成功", r_utc.get("ok") is True, f"event_id={utc_id}")
check("创建返回统一 +08:00", str(created_utc.get("start_time", "")).endswith("+08:00"),
      f"start_time={created_utc.get('start_time')}")
check("Z 入参时刻等价东八区 18:00",
      str(created_utc.get("start_time", "")).startswith("2026-12-01T18:00:00"),
      f"start_time={created_utc.get('start_time')}")

r_back = get(f"/events/{utc_id}")
check("列表/详情读回仍为 +08:00（PG 读回不变成 UTC）",
      str(r_back.get("start_time", "")).endswith("+08:00"),
      f"start_time={r_back.get('start_time')}")
check("读回时刻与创建一致",
      r_back.get("start_time") == created_utc.get("start_time"),
      f"{r_back.get('start_time')} vs {created_utc.get('start_time')}")
delete(f"/events/{utc_id}")  # 清理，避免影响后续列表计数

# ============================================================ 6.5 错误形态统一
print("6.5 参数错误形态统一（非法 ts 应返回 400 + {message, errors}）：")
r_bad_ts = get(f"/events/{event_id}/phase?ts=not-a-time")
check("非法 ts 返回 400（非 422）", r_bad_ts.get("_http_error") == 400,
      f"detail={r_bad_ts.get('detail')}")
detail = r_bad_ts.get("detail") or {}
check("错误形态为 {message, errors}",
      isinstance(detail, dict) and "message" in detail and "errors" in detail,
      f"message={detail.get('message')} errors={detail.get('errors')}")

r_bad_range = get("/events?start_from=abc")
check("非法 start_from 返回 400", r_bad_range.get("_http_error") == 400,
      f"detail={r_bad_range.get('detail')}")

r_bad_body = post("/events", {"event_name": "缺少必填时间的活动"})
check("请求体缺必填字段返回 400", r_bad_body.get("_http_error") == 400,
      f"detail={r_bad_body.get('detail')}")

# 非活动接口保持默认 422 形态（不影响既有前端）
r_other = get("/evaluation?app_name=core-payment&granularity=5m&horizon=24h&folds=abc")
check("非活动接口仍为 422", r_other.get("_http_error") == 422,
      f"http={r_other.get('_http_error')}")

# ============================================================ 7. 删除
print("7. 删除活动：")
r = delete(f"/events/{event_id}")
check("删除成功", r.get("ok") is True, f"message={r.get('message')}")
r = get(f"/events/{event_id}")
check("删除后查询返回 404", r.get("_http_error") == 404)
r = delete(f"/events/{event_id}")
check("重复删除返回 404", r.get("_http_error") == 404, f"detail={r.get('detail')}")

# ============================================================ 汇总
print()
print(f"测试结果：PASS={PASS} FAIL={FAIL}")
print("阶段四活动模块测试完成" if FAIL == 0 else "存在失败用例，请检查上方 [FAIL] 项")
sys.exit(1 if FAIL else 0)
