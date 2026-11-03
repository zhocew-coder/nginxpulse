"""阶段三预测引擎测试。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.forecast import engine as fe
from app.forecast import dataset as fd

# 1. 正常对象：核心支付应用 24h 预测
print("=== 1. 数据加载 ===")
s = fd.load_series("core-payment", "", "5m")
print("点数:", len(s), "质量:", fd.quality_report(s))

print("\n=== 2. 资格检查 ===")
elig = fe.check_eligibility("app", "core-payment", "")
print("allowed:", elig["allowed"], "status:", elig["status"],
      "flags:", elig["risk_flags"])

print("\n=== 3. 执行预测(24h, auto) ===")
res = fe.run_forecast(app_name="core-payment", uri_template="",
                      granularity="5m", horizon="24h",
                      scenario="baseline", model_strategy="auto")
if "error" in res:
    print("预测被拒:", res)
else:
    print("forecast_id:", res["forecast_id"])
    print("模型:", res["model"])
    print("点数:", len(res["points"]))
    print("首点:", res["points"][0])
    print("汇总:", res["summary"])
    print("回测:", res["backtest"])
    print("风险:", res["risk_flags"])

print("\n=== 4. 冷系统预测(应被拒绝) ===")
cold = fe.run_forecast(app_name="cold-archive", uri_template="",
                       granularity="5m", horizon="24h")
print("结果:", cold if "error" in cold else "意外成功")

print("\n=== 5. 冷系统强制预测(应带风险标识) ===")
forced = fe.run_forecast(app_name="cold-archive", uri_template="",
                         granularity="5m", horizon="24h", force=True)
if "error" in forced:
    print("仍失败:", forced)
else:
    print("模型:", forced["model"], "风险:", forced["risk_flags"])
    print("汇总:", forced["summary"])

print("\n=== 6. 指定模型 ETS ===")
ets_res = fe.run_forecast(app_name="core-banking", uri_template="",
                          granularity="1h", horizon="24h",
                          model_strategy="ets")
if "error" in ets_res:
    print("被拒:", ets_res)
else:
    print("模型:", ets_res["model"], "点数:", len(ets_res["points"]))
    print("汇总:", ets_res["summary"])
