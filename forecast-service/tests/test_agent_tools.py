"""阶段五：AI Agent 8 个工具执行测试（Python 层，不依赖服务运行）。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agent.tools import TOOL_SCHEMAS, execute_tool


def show(name, args, keys=None):
    r = execute_tool(name, args)
    if "error" in r:
        print(f"  [{name}] ERROR: {r['error']}")
        return r
    if keys:
        brief = {k: r.get(k) for k in keys if k in r}
    else:
        brief = r
    print(f"  [{name}] OK: {json.dumps(brief, ensure_ascii=False, default=str)[:230]}")
    return r


print("=== 工具 schema 数量 ===")
print(" ", len(TOOL_SCHEMAS), [t["function"]["name"] for t in TOOL_SCHEMAS])

print("\n=== 1. query_transaction_history ===")
show("query_transaction_history", {"app_name": "core-payment"},
     ["app_name", "total_requests", "buckets", "data_completeness"])

print("\n=== 2. evaluate_forecast_eligibility（合格对象）===")
show("evaluate_forecast_eligibility", {"app_name": "core-payment"},
     ["status", "allowed", "predictability"])

print("\n=== 2b. evaluate_forecast_eligibility（冷系统）===")
show("evaluate_forecast_eligibility", {"app_name": "cold-archive"},
     ["status", "allowed", "reasons"])

print("\n=== 3. list_forecastable_objects ===")
show("list_forecastable_objects", {"status": "eligible", "limit": 5},
     ["status", "count"])

print("\n=== 5. query_business_events ===")
ev = show("query_business_events", {"limit": 10}, ["count"])
events = ev.get("events", [])
print("   活动:", [(e["event_id"], e["event_name"], e.get("expected_uplift"))
                   for e in events])

print("\n=== 4. forecast_transaction_volume（基线）===")
fc = show("forecast_transaction_volume",
          {"app_name": "core-payment", "horizon": "24h"},
          ["forecast_id", "scenario", "model"])
fid = fc.get("forecast_id")
print("   汇总:", json.dumps(fc.get("summary", {}), ensure_ascii=False)[:200])

print("\n=== 8. get_forecast_result ===")
if fid:
    show("get_forecast_result", {"forecast_id": fid},
         ["forecast_id", "points_count", "model"])

print("\n=== 7. get_forecast_evaluation ===")
show("get_forecast_evaluation",
     {"app_name": "core-payment", "folds": 2}, ["granularity"])

print("\n=== 6. compare_event_impact ===")
if events:
    eid = events[0]["event_id"]
    show("compare_event_impact",
         {"app_name": "core-payment", "event_id": eid},
         ["event_id", "event_name"])

print("\n=== 异常工具名 ===")
show("no_such_tool", {})

print("\n阶段五工具测试完成")
