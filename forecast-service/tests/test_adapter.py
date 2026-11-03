"""缺口2 验证：用户创建的活动必须能进入活动影响分析。

覆盖链路：
1. adapter.to_business_event 字段适配（MockEvent start/end -> start_time/end_time）
2. adapter.load_events() 读到用户创建的活动（PG/内存双模式）
3. 用户创建的历史同类活动 → estimate_uplift 来源为 history（历史实测）
   验证方式：删除 mock 同类活动后，在 mock 数据中确有真实增幅的窗口上
   创建用户活动，确保 history 只可能来自用户创建的活动
4. 历史实测接近 0/为负时也必须采用（如实测数据），不得静默丢弃
5. 无历史但有计划参数 → 来源为 planned
6. 都没有 → uplift=None（不编造，只出基线）
7. API：POST /predict 带 event_id → 活动增量真实叠加（事件落在预测窗口内）

用法：
    FORECAST_TEST_PORT=8091 python tests/test_adapter.py
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.events.adapter import load_events, to_business_event  # noqa: E402
from app.events.models import TZ, BusinessEvent  # noqa: E402
from app.forecast import event_impact as ei  # noqa: E402

PORT = os.getenv("FORECAST_TEST_PORT", "8091")
BASE = f"http://127.0.0.1:{PORT}/api/forecast/v1"

PASS, FAIL = 0, 0


def check(name: str, ok: bool, extra: str = "") -> None:
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
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"_http_error": e.code,
                "detail": json.loads(e.read().decode("utf-8")).get("detail")}


def get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=180) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"_http_error": e.code,
                "detail": json.loads(e.read().decode("utf-8")).get("detail")}


def delete(path):
    req = urllib.request.Request(BASE + path, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"_http_error": e.code,
                "detail": json.loads(e.read().decode("utf-8")).get("detail")}


# 保证活动存储里有基线 mock 活动（幂等 upsert）
post("/events/init-mock", {})

now = datetime.now(TZ).replace(minute=0, second=0, microsecond=0)

# ============================================================ 1. 字段适配
print("1. adapter.to_business_event 字段适配（MockEvent start/end -> start_time/end_time）：")
mock_like = {"event_id": "evt_alias_check", "event_name": "别名适配检查",
             "event_type": "batch", "start": (now - timedelta(days=3)).isoformat(),
             "end": (now - timedelta(days=2)).isoformat(),
             "target_apps": ["batch-settlement"], "status": "completed"}
ev = to_business_event(mock_like)
check("start/end 被适配成 start_time/end_time",
      ev.start_time is not None and ev.end_time is not None,
      f"start_time={ev.start_time.isoformat()} end_time={ev.end_time.isoformat()}")
check("BusinessEvent 实例原样返回", to_business_event(ev) is ev)

# ============================================================ 2. 用户创建历史活动
print("2. 用户创建历史同类活动（mock 真实增幅窗口，隔离 mock 活动）：")
# 取 mock 月末批量活动的窗口（mock 序列在该窗口上有真实增幅）
mock_batch = get("/events/evt_monthly_batch")
check("读到 mock 月末批量活动", mock_batch.get("event_id") == "evt_monthly_batch",
      f"窗口={mock_batch.get('start_time')} ~ {mock_batch.get('end_time')}")
win_start = mock_batch.get("start_time")
win_end = mock_batch.get("end_time")
# 删除 mock 活动，保证 history 候选只剩用户创建的活动（严格隔离）
delete("/events/evt_monthly_batch")

hist_payload = {
    "event_name": "用户创建-历史月末批量",
    "event_type": "batch",
    "start_time": win_start,
    "end_time": win_end,
    "target_apps": ["core-banking"],
    "business_type": "清算批处理",
    "impact_level": "medium",
    "expected_uplift": None,      # 无计划参数，增幅应来自历史实测
    "event_owner": "用户-测试",
    "status": "completed",
}
r = post("/events", hist_payload)
check("历史活动创建成功", r.get("ok") is True,
      f"event_id={(r.get('event') or {}).get('event_id')}")
hist_id = (r.get("event") or {}).get("event_id", "")

# ============================================================ 3. load_events
print("3. adapter.load_events 读到用户创建的活动（缺口2 核心）：")
events = load_events()
ids = [e.event_id for e in events]
check("load_events 返回非空", len(events) > 0, f"共 {len(events)} 个")
check("包含用户创建的历史活动", hist_id in ids,
      f"用户活动={hist_id} 在列表中" if hist_id in ids else f"ids={ids}")
srcs = {e.data_source for e in events}
check("数据来源含 manual（用户创建）", "manual" in srcs, f"sources={srcs}")

# ============================================================ 4. 历史增幅来源
print("4. estimate_uplift 来源为 history（增幅只能来自用户创建的历史活动）：")
upcoming_payload = {
    "event_name": "用户创建-即将开始的批量活动",
    "event_type": "batch",
    "start_time": (now + timedelta(days=5)).isoformat(),
    "end_time": (now + timedelta(days=6)).isoformat(),
    "target_apps": ["core-banking"],
    "impact_level": "medium",
    "expected_uplift": None,
    "event_owner": "用户-测试",
    "status": "confirmed",
}
r2 = post("/events", upcoming_payload)
upcoming_id = (r2.get("event") or {}).get("event_id", "")
check("未来活动创建成功", r2.get("ok") is True, f"event_id={upcoming_id}")

upcoming = BusinessEvent.from_dict(r2.get("event", {}))
up = ei.estimate_uplift("core-banking", "", upcoming)
print(f"     uplift={up['uplift']} source={up['source']} confidence={up['confidence']}")
print(f"     reason={up['reason']}")
check("增幅来源为 history（用户创建的历史活动生效）", up["source"] == "history",
      f"source={up['source']}")
check("历史实测增幅为正（mock 窗口确有增幅）", (up["uplift"] or 0) > 0,
      f"uplift={up['uplift']}")

# ============================================================ 4b. 实测接近 0 也须采用
print("4b. 历史实测接近 0/为负时不得静默丢弃：")
noise_hist_payload = {
    "event_name": "用户创建-无真实增幅窗口的历史活动",
    "event_type": "promotion",
    "start_time": (now - timedelta(days=30)).isoformat(),
    "end_time": (now - timedelta(days=29)).isoformat(),
    "target_apps": ["core-payment"],
    "impact_level": "low",
    "expected_uplift": None,
    "event_owner": "用户-测试",
    "status": "completed",
}
r3 = post("/events", noise_hist_payload)
noise_hist_id = (r3.get("event") or {}).get("event_id", "")
noise_future = BusinessEvent.from_dict({
    "event_id": "evt_noise_future", "event_name": "未来推广活动",
    "event_type": "promotion",
    "start_time": (now + timedelta(days=7)).isoformat(),
    "end_time": (now + timedelta(days=8)).isoformat(),
    "target_apps": ["core-payment"], "status": "confirmed",
})
up3 = ei.estimate_uplift("core-payment", "", noise_future)
print(f"     uplift={up3['uplift']} source={up3['source']} confidence={up3['confidence']}")
print(f"     reason={up3['reason']}")
check("实测接近 0 时仍标记 history（如实测数据）", up3["source"] == "history",
      f"source={up3['source']}")
check("uplift 非 None（给出实测值）", up3["uplift"] is not None, f"uplift={up3['uplift']}")
check("弱证据时置信度降级为 low", up3["confidence"] == "low",
      f"confidence={up3['confidence']}")

# ============================================================ 5. 计划参数来源
print("5. estimate_uplift 来源为 planned（仅有计划参数）：")
planned_payload = {
    "event_name": "用户创建-有计划增幅的活动",
    "event_type": "launch",
    "start_time": (now + timedelta(days=10)).isoformat(),
    "end_time": (now + timedelta(days=11)).isoformat(),
    "target_apps": ["std-crm"],
    "impact_level": "medium",
    "expected_uplift": 1.2,
    "event_owner": "用户-测试",
    "status": "confirmed",
}
r4 = post("/events", planned_payload)
planned_id = (r4.get("event") or {}).get("event_id", "")
planned_ev = BusinessEvent.from_dict(r4.get("event", {}))
up5 = ei.estimate_uplift("std-crm", "", planned_ev)
print(f"     uplift={up5['uplift']} source={up5['source']} reason={up5['reason']}")
check("增幅来源为 planned", up5["source"] == "planned", f"source={up5['source']}")
check("planned 增幅等于计划值 1.2", up5["uplift"] == 1.2, f"uplift={up5['uplift']}")

# ============================================================ 6. 无依据不得编造
print("6. 无历史且无计划参数 → 不得编造：")
novel_payload = {
    "event_name": "用户创建-全新类型无依据活动",
    "event_type": "holiday",
    "start_time": (now + timedelta(days=20)).isoformat(),
    "end_time": (now + timedelta(days=22)).isoformat(),
    "target_apps": ["cold-archive"],
    "impact_level": "low",
    "expected_uplift": None,
    "event_owner": "用户-测试",
    "status": "confirmed",
}
r6 = post("/events", novel_payload)
novel_id = (r6.get("event") or {}).get("event_id", "")
novel_ev = BusinessEvent.from_dict(r6.get("event", {}))
up6 = ei.estimate_uplift("cold-archive", "", novel_ev)
print(f"     uplift={up6['uplift']} source={up6['source']} reason={up6['reason']}")
check("uplift 为 None（不编造）", up6["uplift"] is None, f"uplift={up6['uplift']}")
check("source=none", up6["source"] == "none")
check("reason 明确说明数据不足", "数据不足" in up6["reason"] or "不得编造" in up6["reason"],
      f"reason={up6['reason']}")

# ============================================================ 7. API 活动调整预测
print("7. POST /predict 带 event_id（用户创建的活动进入影响分析，增量真实生效）：")
# 先取基线预测，用预测窗口起点构造活动，保证活动落在预测窗口内
r_base = post("/predict", {
    "app_name": "core-banking", "uri_template": "",
    "granularity": "5m", "horizon": "24h",
    "model_strategy": "seasonal_naive",
})
first_ts = datetime.fromisoformat(r_base["points"][0]["timestamp"])
print(f"     预测窗口起点={first_ts.isoformat()}（按此构造活动窗口）")
inwin_payload = {
    "event_name": "用户创建-预测窗口内的批量活动",
    "event_type": "batch",
    "start_time": (first_ts + timedelta(hours=2)).isoformat(),
    "end_time": (first_ts + timedelta(hours=10)).isoformat(),
    "preheat_start": first_ts.isoformat(),
    "cooldown_end": (first_ts + timedelta(hours=14)).isoformat(),
    "target_apps": ["core-banking"],
    "impact_level": "medium",
    "expected_uplift": None,
    "event_owner": "用户-测试",
    "status": "confirmed",
}
r7 = post("/events", inwin_payload)
inwin_id = (r7.get("event") or {}).get("event_id", "")
check("窗口内活动创建成功", r7.get("ok") is True, f"event_id={inwin_id}")

r8 = post("/predict", {
    "app_name": "core-banking", "uri_template": "",
    "granularity": "5m", "horizon": "24h",
    "model_strategy": "seasonal_naive",
    "event_id": inwin_id,
})
if "_http_error" in r8:
    check("活动调整预测成功", False, f"HTTP {r8['_http_error']} {r8['detail']}")
else:
    ev_info = r8.get("event") or {}
    up8 = ev_info.get("uplift_estimate", {})
    s = r8.get("summary", {})
    check("预测返回 event 块", bool(ev_info),
          f"event_id={ev_info.get('event_id')} scenario={r8.get('scenario')}")
    check("scenario 自动置为 event_adjusted", r8.get("scenario") == "event_adjusted",
          f"scenario={r8.get('scenario')}")
    check("uplift 来源为 history（服务端也走用户活动）", up8.get("source") == "history",
          f"source={up8.get('source')} uplift={up8.get('uplift')}")
    check("活动增量真实叠加", (s.get("total_event_increment") or 0) != 0,
          f"total_increment={s.get('total_event_increment')}")
    check("调整后总量 ≠ 基线", s.get("total_event_adjusted") != s.get("total_baseline"),
          f"base={s.get('total_baseline')} adj={s.get('total_event_adjusted')}")
    m1 = (ev_info.get("diff_analysis") or {}).get("method1_vs_baseline", {})
    check("差分①给出增幅", m1.get("uplift_ratio") is not None,
          f"uplift_ratio={m1.get('uplift_ratio')} 峰值增量={m1.get('peak_increment')}")
    check("含多情景对比", "scenarios" in ev_info and
          ev_info["scenarios"].get("available") is True)
    print(f"     基线总量={s.get('total_baseline')} 调整后={s.get('total_event_adjusted')} "
          f"增量={s.get('total_event_increment')}")
    print(f"     差分①增幅={m1.get('uplift_ratio')} 差分③正式期增幅="
          f"{(ev_info.get('diff_analysis') or {}).get('method3_before_after', {}).get('active_growth_vs_baseline')}")

# ============================================================ 8. 清理
print("8. 清理测试活动并还原 mock 活动：")
for eid in (hist_id, upcoming_id, noise_hist_id, planned_id, novel_id, inwin_id):
    if eid:
        delete(f"/events/{eid}")
post("/events/init-mock", {})   # 还原被删除的 evt_monthly_batch
restored = get("/events/evt_monthly_batch")
check("mock 活动已还原", restored.get("event_id") == "evt_monthly_batch",
      f"event_id={restored.get('event_id')}")

print()
print(f"测试结果：PASS={PASS} FAIL={FAIL}")
print("缺口2 适配层测试完成" if FAIL == 0 else "存在失败用例，请检查上方 [FAIL] 项")
sys.exit(1 if FAIL else 0)
