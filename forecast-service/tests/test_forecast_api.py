"""阶段三预测 API 测试（真实 HTTP 调用）。"""
import json
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8090/api/forecast/v1"


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


# 1. 正常预测
print("1. 预测 core-payment 24h:")
r1 = post("/predict", {"app_name": "core-payment", "uri_template": "",
                       "granularity": "5m", "horizon": "24h",
                       "scenario": "baseline", "model_strategy": "auto"})
if "_http_error" in r1:
    print("   失败:", r1)
else:
    print("   forecast_id:", r1["forecast_id"])
    print("   模型:", r1["model"], "点数:", len(r1["points"]))
    print("   总量:", r1["summary"]["total_baseline"])
    print("   回测改善:", r1["backtest"].get(r1["model"], {}).get(
        "improvement_vs_baseline"))
    fid = r1["forecast_id"]

    # 2. 查询预测结果
    print("2. 查询预测结果:")
    r2 = get(f"/result/{fid}")
    if "_http_error" in r2:
        print("   失败:", r2)
    else:
        print("   取回点数:", len(r2.get("points", [])), "模型:", r2.get("model"))

# 3. 回测指标
print("3. 回测指标:")
r3 = get("/evaluation?app_name=core-payment&granularity=5m&horizon=24h&folds=3")
if "_http_error" in r3:
    print("   失败:", r3)
else:
    for m, v in r3["backtest"].items():
        print(f"   {m}: MAE={v['mae']} WAPE={v['wape']} "
              f"sMAPE={v['smape']} 覆盖率={v['interval_coverage']} "
              f"改善={v['improvement_vs_baseline']}")

# 4. 冷系统应被拒绝
print("4. 冷系统预测(应被拒绝):")
r4 = post("/predict", {"app_name": "cold-archive", "uri_template": "",
                       "granularity": "5m", "horizon": "24h"})
if "_http_error" in r4:
    print("   正确拒绝 HTTP", r4["_http_error"])
    print("   原因:", r4["detail"].get("reasons"))
else:
    print("   意外成功:", r4.get("forecast_id"))

# 5. 冷系统强制预测
print("5. 冷系统强制预测(应带风险标识):")
r5 = post("/predict", {"app_name": "cold-archive", "uri_template": "",
                       "granularity": "5m", "horizon": "24h", "force": True})
if "_http_error" in r5:
    print("   失败:", r5)
else:
    print("   模型:", r5["model"], "风险:", r5["risk_flags"])

print("阶段三 API 测试完成")
