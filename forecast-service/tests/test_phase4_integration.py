"""阶段四端到端联调：活动日历 + 活动影响预测。"""
import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

BASE = "http://127.0.0.1:8090/api/forecast/v1"
TZ = timezone(timedelta(hours=8))


def post(path, payload):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=200) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"_err": e.code, "detail": str(e.read().decode("utf-8")[:300])}


def get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=200) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"_err": e.code, "detail": str(e.read().decode("utf-8")[:300])}


# 1. 初始化 mock 活动
print("1. 初始化 mock 活动:")
r = post("/events/init-mock", {})
print("   count:", r.get("count") if isinstance(r, dict) else r)
print("   活动:", r.get("event_ids") if isinstance(r, dict) else "")

# 2. 活动列表
print("\n2. 活动列表:")
lst = get("/events?limit=20")
if isinstance(lst, dict) and "events" in lst:
    for e in lst["events"]:
        print(f"   - {e.get('event_id')} {e.get('event_name')} "
              f"({e.get('event_type')}) 增幅={e.get('expected_uplift')} "
              f"置信度={e.get('confidence')} 应用={e.get('target_apps')}")

# 3. 创建一个“未来”活动（预测窗口内），验证增量真实生效
now = datetime.now(TZ)
start = (now + timedelta(hours=14)).replace(minute=0, second=0, microsecond=0)
end = start + timedelta(hours=6)
print(f"\n3. 创建未来活动 (core-banking, {start:%Y-%m-%d %H:%M} ~ {end:%H:%M}):")
new_evt = {
    "event_name": "联调测试-月末批量清算",
    "event_type": "batch",
    "start_time": start.isoformat(),
    "end_time": end.isoformat(),
    "preheat_start": (start - timedelta(hours=2)).isoformat(),
    "cooldown_end": (end + timedelta(hours=4)).isoformat(),
    "target_apps": ["core-banking"],
    "target_uris": [],
    "business_type": "清算",
    "impact_level": "high",
    "expected_uplift": None,   # 不标注，考验是否从历史估出
    "event_owner": "联调测试",
    "data_source": "mock",
    "status": "confirmed",
}
created = post("/events", new_evt)
if "_err" in created:
    print("   创建失败:", created)
    raise SystemExit(1)
eid = created.get("event_id") or created.get("event", {}).get("event_id")
print("   event_id:", eid)

# 4. 用该活动做活动专项预测
print(f"\n4. 活动专项预测 (core-banking + {eid}):")
r = post("/predict", {
    "app_name": "core-banking", "uri_template": "",
    "granularity": "5m", "horizon": "24h",
    "scenario": "event_adjusted", "model_strategy": "seasonal_naive",
    "event_id": eid,
})
if "_err" in r:
    print("   预测失败:", r)
    raise SystemExit(1)
print("   模型:", r.get("model"))
print("   基线总量:", r["summary"]["total_baseline"])
print("   调整后总量:", r["summary"]["total_event_adjusted"])
print("   活动增量:", r["summary"]["total_event_increment"])
ev = r.get("event") or {}
ue = ev.get("uplift_estimate", {})
print("   uplift:", ue.get("uplift"), "来源:", ue.get("source"),
      "置信度:", ue.get("confidence"))
print("   说明:", ue.get("reason"))
da = ev.get("diff_analysis", {})
m1 = da.get("method1_vs_baseline", {})
print("   差分①增幅:", m1.get("uplift_ratio"),
      "峰值增量:", m1.get("peak_increment"),
      "影响点数:", m1.get("impact_duration_points"))
m3 = da.get("method3_before_after", {})
print("   差分③基线/预热/正式/回落:", m3.get("pre_event_baseline"),
      m3.get("preheat_avg"), m3.get("active_avg"), m3.get("cooldown_avg"))
m4 = da.get("method4_did", {})
print("   差分④DID可用:", m4.get("available"),
      str(m4.get("reason", ""))[:50])
sc = ev.get("scenarios", {})
print("   多情景可用:", sc.get("available"))
if sc.get("available"):
    print("   情景增量:", {k: v["increment"] for k, v in sc["scenarios"].items()})

# 5. 阶段查询
print("\n5. 活动阶段查询:")
from urllib.parse import quote
# 注意：isoformat 含 "+08:00"，URL 中 + 会被解析为空格，必须编码
ph = get(f"/events/{eid}/phase?ts={quote(start.isoformat())}")
print("   正式期时点:", ph.get("phase"), ph.get("phase_label"),
      "uplift:", ph.get("uplift"))
ph2 = get(f"/events/{eid}/phase?ts="
          f"{quote((start - timedelta(hours=1)).isoformat())}")
print("   预热期时点:", ph2.get("phase"), ph2.get("phase_label"),
      "uplift:", ph2.get("uplift"))
ph3 = get(f"/events/{eid}/phase?ts="
          f"{quote((end + timedelta(hours=2)).isoformat())}")
print("   回落期时点:", ph3.get("phase"), ph3.get("phase_label"),
      "uplift:", ph3.get("uplift"))

print("\n阶段四联调测试完成")
