"""阶段四：活动影响建模与差分分析测试。

重点验证需求 §4.6 的硬约束：
  - 有历史同类活动数据 → 用历史实测增幅
  - 无历史且无计划参数 → **不得编造**，只输出基线并标注数据不足
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.forecast import engine as fe
from app.forecast import dataset as fd
from app.forecast import event_impact as ei

# 取 mock 活动
series = fd.load_series("batch-settlement", "", "5m")
ts0 = series["timestamp"].iloc[0].to_pydatetime()
ts1 = series["timestamp"].iloc[-1].to_pydatetime()
from app.mock.generator import build_mock_events
events = build_mock_events(ts0, ts1)
print("Mock活动:")
for e in events:
    print(f"  - {e.event_name} ({e.event_type}) {e.start} ~ {e.end} "
          f"target={e.target_apps}")

# 1. 月末批量活动（历史数据内应有 8-28 同类活动）
batch_evt = [e for e in events if e.event_type == "batch"]
if batch_evt:
    e = batch_evt[0]
    print(f"\n1. 月末批量活动 uplift 估计 ({e.event_name}):")
    up = ei.estimate_uplift("batch-settlement", "", e)
    print("   uplift:", up["uplift"], "来源:", up["source"],
          "置信度:", up["confidence"])
    print("   说明:", up["reason"])

# 2. 双十一（历史数据外 → 应判定数据不足，不得编造）
s11 = [e for e in events if e.event_type == "marketing"]
if s11:
    e = s11[0]
    print(f"\n2. 双十一活动 uplift 估计 ({e.event_name}):")
    up = ei.estimate_uplift("core-payment", "", e)
    print("   uplift:", up["uplift"], "来源:", up["source"],
          "置信度:", up["confidence"])
    print("   说明:", up["reason"])

# 3. 带活动执行预测（活动调整）
if batch_evt:
    e = batch_evt[0]
    print(f"\n3. 活动调整预测 (batch-settlement + {e.event_name}):")
    res = fe.run_forecast(app_name="batch-settlement", uri_template="",
                          granularity="5m", horizon="24h",
                          scenario="event_adjusted",
                          model_strategy="seasonal_naive", event=e)
    if "error" in res:
        print("   失败:", res)
    else:
        ev = res.get("event")
        print("   基线总量:", res["summary"]["total_baseline"])
        print("   调整后总量:", res["summary"]["total_event_adjusted"])
        print("   活动增量:", res["summary"]["total_event_increment"])
        print("   uplift:", ev["uplift_estimate"]["uplift"],
              "来源:", ev["uplift_estimate"]["source"])
        m1 = ev["diff_analysis"]["method1_vs_baseline"]
        print("   差分①增幅:", m1["uplift_ratio"],
              "峰值增量:", m1["peak_increment"],
              "影响点数:", m1["impact_duration_points"])
        print("   差分③前后:", ev["diff_analysis"]["method3_before_after"])
        print("   差分④DID:", ev["diff_analysis"]["method4_did"]["available"],
              ev["diff_analysis"]["method4_did"].get("reason", "")[:40])
        print("   多情景:", ev["scenarios"])

# 4. 阶段判定
print("\n4. 活动阶段判定:")
if batch_evt:
    e = batch_evt[0]
    import pandas as pd
    for label, t in [("活动前", e.start - pd.Timedelta(hours=2)),
                     ("正式期", e.start + pd.Timedelta(minutes=30)),
                     ("回落后", e.end + pd.Timedelta(hours=1))]:
        print(f"   {label}: {ei.event_phase_at(e, t)}")

# 5. 活动落在预测窗口内 —— 验证增量、差分、多情景真实生效
print("\n5. 活动在预测窗口内（验证增量生效）:")
import pandas as pd
from app.mock.generator import MockEvent
now = series["timestamp"].iloc[-1]
evt = MockEvent(
    event_id="evt_test_window",
    event_name="测试窗口内活动",
    event_type="batch",
    start=now + pd.Timedelta(hours=2),
    end=now + pd.Timedelta(hours=8),
    preheat_start=now + pd.Timedelta(minutes=30),
    cooldown_end=now + pd.Timedelta(hours=12),
    # 用 core-banking：月末批量的目标应用之一，且白天有稳定流量
    # （batch-settlement 白天基线为 0，增量必然为 0，无法演示叠加效果）
    target_apps=["core-banking"],
    impact_level="high",
    expected_uplift=None,
    status="confirmed",
)
res5 = fe.run_forecast(app_name="core-banking", uri_template="",
                       granularity="5m", horizon="24h",
                       scenario="event_adjusted",
                       model_strategy="seasonal_naive", event=evt)
if "error" in res5:
    print("   失败:", res5)
else:
    ev = res5["event"]
    print("   uplift:", ev["uplift_estimate"]["uplift"],
          "来源:", ev["uplift_estimate"]["source"])
    print("   基线总量:", res5["summary"]["total_baseline"])
    print("   调整后总量:", res5["summary"]["total_event_adjusted"])
    print("   活动增量:", res5["summary"]["total_event_increment"])
    m1 = ev["diff_analysis"]["method1_vs_baseline"]
    print("   差分①增幅:", m1["uplift_ratio"],
          "峰值增量:", m1["peak_increment"],
          "影响点数:", m1["impact_duration_points"])
    m3 = ev["diff_analysis"]["method3_before_after"]
    print("   差分③基线/预热/正式/回落:", m3["pre_event_baseline"],
          m3["preheat_avg"], m3["active_avg"], m3["cooldown_avg"])
    print("   差分③预热增幅:", m3["preheat_growth_vs_baseline"],
          "正式增幅:", m3["active_growth_vs_baseline"],
          "回落衰减:", m3["cooldown_decay_rate"])
    sc = ev["scenarios"]
    if sc.get("available"):
        print("   情景增量:", {k: v["increment"] for k, v in sc["scenarios"].items()})
