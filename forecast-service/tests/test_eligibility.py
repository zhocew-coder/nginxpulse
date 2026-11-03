"""阶段二资格引擎冒烟测试。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import datasource
from app.eligibility import engine
from app.eligibility.rules import default_rules

df = datasource.get_history_series()
print("时序行数:", len(df), "对象数:", df.groupby(["app_name", "uri_template"]).ngroups)

cases = [
    ("core-payment", "", "app", "核心应用-应eligible"),
    ("core-payment", "/api/transaction/submit", "uri", "核心URL-应eligible"),
    ("cold-archive", "", "app", "冷系统-应cold"),
    ("cold-archive", "/api/old/query", "uri", "冷URL-应cold"),
    ("batch-settlement", "", "app", "批处理-夜间集中"),
    ("std-crm", "/api/legacy/archive", "uri", "低频URL-应probation/cold"),
    ("std-loan", "", "app", "普通应用-应eligible/probation"),
]

for app, uri, level, desc in cases:
    sub = df[(df.app_name == app) & (df.uri_template == uri)]
    if sub.empty:
        print(f"{desc:20s} -> 无数据")
        continue
    res = engine.evaluate_object(
        series=sub["request_count"], timestamps=sub["timestamp"],
        level=level, app_name=app, uri_template=uri, rules=default_rules,
    )
    seas = res.features["weekly_seasonality_score"]
    print(f"{desc:20s} -> {res.status:20s} score={res.eligibility_score:6.2f} "
          f"req={res.total_requests} act_days={res.active_days} seas={seas:.2f} "
          f"pred={res.predictability}")
