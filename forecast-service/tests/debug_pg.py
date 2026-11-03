"""诊断：为什么 save_results 写入 PG 失败（异常被静默吞掉）。"""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from app.core import datasource
from app.eligibility import engine
from app.eligibility.rules import default_rules
from app.storage import eligibility_store

print("DSN:", settings.dsn)

df = datasource.get_history_series()
print("时序行数:", len(df))

# 构造 1 个结果用于诊断
res = engine.evaluate_object(
    series=df[df.app_name == "core-payment"]["request_count"],
    timestamps=df[df.app_name == "core-payment"]["timestamp"],
    level="app", app_name="core-payment", uri_template="", rules=default_rules,
)
from app.api.main import _result_to_dict
r = _result_to_dict(res)
r["config_version"] = "v1"
r["data_source"] = "mock"
print("结果 keys:", sorted(r.keys()))
print("reasons type:", type(r["reasons"]), r["reasons"])
print("avg_interarrival_minutes:", r["avg_interarrival_minutes"])

# 直接尝试 PG 写入，捕获真实异常
import psycopg2
from datetime import datetime, timezone
conn = psycopg2.connect(settings.dsn, connect_timeout=5)
cur = conn.cursor()
try:
    cur.execute("""
        INSERT INTO forecast_eligibility
            (level, app_name, uri_template, total_requests, active_days,
             active_day_ratio, nonzero_buckets, nonzero_bucket_ratio,
             data_completeness, avg_daily_requests, max_daily_requests,
             avg_interarrival_minutes, weekly_seasonality_score,
             monthly_seasonality_score, history_days, status, predictability,
             eligibility_score, reasons, bucket_count, missing_buckets,
             night_concentration, override_status, override_reason, override_by,
             override_at, event_included, event_confidence, config_version,
             data_source, evaluated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (level, app_name, uri_template) DO UPDATE SET status=EXCLUDED.status
    """, (
        r["level"], r["app_name"], r["uri_template"],
        r["total_requests"], r["active_days"],
        r["active_day_ratio"], r["nonzero_buckets"], r["nonzero_bucket_ratio"],
        r["data_completeness"], r["avg_daily_requests"], r["max_daily_requests"],
        r["avg_interarrival_minutes"], r["weekly_seasonality_score"],
        r["monthly_seasonality_score"], r["history_days"], r["status"],
        r["predictability"], r["eligibility_score"], r["reasons"],
        r["bucket_count"], r["missing_buckets"], r["night_concentration"],
        r.get("override_status"), r.get("override_reason"),
        r.get("override_by"), r.get("override_at"),
        r["event_included"], r["event_confidence"],
        r["config_version"], r["data_source"], datetime.now(timezone.utc),
    ))
    conn.commit()
    print("INSERT 成功")
except Exception:
    print("INSERT 失败:")
    traceback.print_exc()
    conn.rollback()
cur.execute("SELECT count(*) FROM forecast_eligibility")
print("行数:", cur.fetchone()[0])
conn.close()
