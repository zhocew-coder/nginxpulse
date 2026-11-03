"""FAIL-01 判别用例（真实 HTTP 调用）。

验收标准（docs/forecast/acceptance-regression.md）：
1. backtest interval_coverage 落在 [0.90, 0.95]
2. width/pt = (upper-lower)/baseline_forecast：中期（24 步）< 2.0，远端（48 步）< 3.0
3. lower_bound=0 的点占比 < 50%

判别用例：POST /predict (std-crm, 4h, baseline)

用法：
    FORECAST_TEST_PORT=8090 python tests/test_fail01_intervals.py
"""
import json
import os
import sys
import urllib.error
import urllib.request

PORT = os.getenv("FORECAST_TEST_PORT", "8090")
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
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"_http_error": e.code,
                "detail": json.loads(e.read().decode("utf-8")).get("detail")}


print("FAIL-01 判别用例：POST /predict std-crm 4h baseline")
r = post("/predict", {"app_name": "std-crm", "uri_template": "",
                      "granularity": "5m", "horizon": "4h",
                      "scenario": "baseline", "model_strategy": "auto"})
if "_http_error" in r:
    check("预测请求成功", False, f"HTTP {r['_http_error']} {r['detail']}")
    sys.exit(1)

points = r["points"]
check("48 点预测", len(points) == 48, f"点数={len(points)}")

# ---- 目标 1：backtest 覆盖率 [0.90, 0.95] ----
cov = None
for m, v in (r.get("backtest") or {}).items():
    cov = v.get("interval_coverage")
    print(f"     模型={m} interval_coverage={cov} mae={v.get('mae')}")
check("backtest 覆盖率在 [0.90, 0.95]", cov is not None and 0.90 <= cov <= 0.95,
      f"coverage={cov}")

# ---- 目标 2/3：宽度倍数与触零占比 ----
widths, zero_cnt, over2 = [], 0, 0
for p in points:
    pt = p["baseline_forecast"]
    lo, hi = p["lower_bound"], p["upper_bound"]
    if lo <= 0:
        zero_cnt += 1
    if pt > 0:
        w = (hi - lo) / pt
        widths.append(w)
        if w > 2.0:
            over2 += 1

w_mid = sum(widths[:24]) / max(len(widths[:24]), 1)
w_far = widths[-1] if widths else 0.0
w_all = sum(widths) / max(len(widths), 1)
zero_frac = zero_cnt / len(points)

print(f"     width/pt: 均值={w_all:.2f} 中期24步={w_mid:.2f} 末点48步={w_far:.2f}")
print(f"     >2倍点数={over2}/{len(points)}  lower_bound=0 点数={zero_cnt}/{len(points)}")

check("width/pt 中期(24步) < 2.0", w_mid < 2.0, f"w@24={w_mid:.2f}")
check("width/pt 远端(48步) < 3.0", w_far < 3.0, f"w@48={w_far:.2f}")
check("lower_bound=0 占比 < 50%", zero_frac < 0.5, f"zero={zero_frac:.1%}")
check("区间宽度 >2 倍点预测的点数明显下降", over2 < len(points) / 2,
      f"over2={over2}/{len(points)}")

print(f"\n测试结果：PASS={PASS} FAIL={FAIL}")
print("FAIL-01 判别用例通过" if FAIL == 0 else "FAIL-01 判别用例未通过")
sys.exit(1 if FAIL else 0)
