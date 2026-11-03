"""预测结果存储（内存 + PostgreSQL 双模式）。"""
from __future__ import annotations

import json
import math
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional

from ..core.config import settings

_mem_lock = threading.Lock()
_mem_forecasts: Dict[str, dict] = {}
_schema_ready = False


def _pg():
    """尝试连 PG，失败返回 None。"""
    try:
        import psycopg2
        return psycopg2.connect(settings.dsn, connect_timeout=3)
    except Exception:
        return None


def init_schema() -> None:
    global _schema_ready
    conn = _pg()
    if conn is None:
        _schema_ready = True
        return
    try:
        from pathlib import Path
        sql = Path(__file__).resolve().parents[2] / "sql" / "002_forecast.sql"
        with conn.cursor() as cur:
            with open(sql) as f:
                cur.execute(f.read())
        conn.commit()
        _schema_ready = True
    except Exception as e:
        print(f"[forecast_store] init_schema skipped: {e}")
        _schema_ready = True
    finally:
        conn.close()


def _clean(obj):
    """递归清理 NaN/Inf —— PostgreSQL 的 jsonb 不接受 NaN 字面量。"""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
    return obj


def _dump(obj) -> str:
    return json.dumps(_clean(obj), ensure_ascii=False, allow_nan=False)


def save_forecast(result: dict) -> None:
    with _mem_lock:
        _mem_forecasts[result["forecast_id"]] = dict(result)
    conn = _pg()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO forecast_results
                    (forecast_id, level, app_name, uri_template, metric, granularity,
                     horizon, scenario, model, model_strategy, points, summary,
                     quality, backtest, eligibility, risk_flags, data_source,
                     history_range, generated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (forecast_id) DO UPDATE SET
                    points=EXCLUDED.points, summary=EXCLUDED.summary,
                    generated_at=EXCLUDED.generated_at
            """, (
                result["forecast_id"],
                "uri" if result.get("uri_template") else "app",
                result.get("app_name"), result.get("uri_template", ""),
                result.get("metric", "request_count"),
                result.get("granularity", "5m"), result.get("horizon"),
                result.get("scenario", "baseline"), result.get("model"),
                result.get("model_strategy", "auto"),
                _dump(result.get("points", [])),
                _dump(result.get("summary", {})),
                _dump(result.get("quality", {})),
                _dump(result.get("backtest", {})),
                _dump(result.get("eligibility", {})),
                result.get("risk_flags", []),
                result.get("data_source", "mock"),
                _dump(result.get("history_range", {})),
                datetime.now(timezone.utc),
            ))
        conn.commit()
    except Exception as e:
        print(f"[forecast_store] save_forecast PG skipped: {e}")
    finally:
        conn.close()


def get_forecast(forecast_id: str) -> Optional[dict]:
    with _mem_lock:
        r = _mem_forecasts.get(forecast_id)
    if r:
        return r
    conn = _pg()
    if conn is None:
        return None
    try:
        import psycopg2.extras
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM forecast_results WHERE forecast_id=%s",
                        (forecast_id,))
            row = cur.fetchone()
        return dict(row) if row else None
    except Exception:
        return None
    finally:
        conn.close()


def list_forecasts(app_name: Optional[str] = None, limit: int = 50) -> List[dict]:
    conn = _pg()
    if conn is not None:
        try:
            import psycopg2.extras
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                sql = "SELECT forecast_id, app_name, uri_template, model, scenario, generated_at FROM forecast_results"
                params = []
                if app_name:
                    sql += " WHERE app_name=%s"; params.append(app_name)
                sql += " ORDER BY generated_at DESC LIMIT %s"
                params.append(limit)
                cur.execute(sql, params)
                return [dict(r) for r in cur.fetchall()]
        except Exception:
            pass
        finally:
            conn.close()
    with _mem_lock:
        rows = [{"forecast_id": v["forecast_id"], "app_name": v.get("app_name"),
                 "uri_template": v.get("uri_template"), "model": v.get("model"),
                 "scenario": v.get("scenario"),
                 "generated_at": v.get("generated_at")}
                for v in _mem_forecasts.values()]
    if app_name:
        rows = [r for r in rows if r["app_name"] == app_name]
    return rows[-limit:]
