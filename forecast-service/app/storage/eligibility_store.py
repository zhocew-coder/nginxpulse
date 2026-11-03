"""预测资格存储层。

双模式：
- 真实 PG 可用时落库（生产/联调）
- PG 不可用时内存后备（mock 开发验证，进程内持久）

这样 USE_MOCK=true 且未映射 PG 端口时，评估/列表/覆盖/历史全部可验证。
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional

from ..core.config import settings


# ---------------- 内存后备存储 ----------------
_mem_lock = threading.Lock()
_mem_results: Dict[str, dict] = {}   # key -> 评估结果
_mem_history: List[dict] = []        # 资格变化历史
_schema_ready = False


def _key(level: str, app_name: str, uri_template: str) -> str:
    return f"{level}|{app_name}|{uri_template}"


def _pg_available() -> bool:
    try:
        import psycopg2  # noqa
        return True
    except Exception:
        return False


def _try_pg_connect():
    """尝试连真实 PG，成功返回连接，失败返回 None。"""
    if not _pg_available():
        return None
    try:
        import psycopg2
        return psycopg2.connect(settings.dsn, connect_timeout=3)
    except Exception:
        return None


def init_schema() -> None:
    """建表（PG 可用时）。内存模式跳过。"""
    global _schema_ready
    conn = _try_pg_connect()
    if conn is None:
        _schema_ready = True  # 内存模式
        return
    try:
        from pathlib import Path
        sql = Path(__file__).resolve().parents[2] / "sql" / "001_eligibility.sql"
        with conn.cursor() as cur:
            with open(sql) as f:
                cur.execute(f.read())
        conn.commit()
        _schema_ready = True
    except Exception as e:
        print(f"[storage] init_schema skipped: {e}")
        _schema_ready = True
    finally:
        conn.close()


def save_results(results: List[dict]) -> None:
    """批量保存评估结果。"""
    for r in results:
        _mem_results[_key(r["level"], r["app_name"], r["uri_template"])] = dict(r)
    conn = _try_pg_connect()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            for r in results:
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
                    ON CONFLICT (level, app_name, uri_template) DO UPDATE SET
                        total_requests=EXCLUDED.total_requests,
                        active_days=EXCLUDED.active_days,
                        status=EXCLUDED.status,
                        eligibility_score=EXCLUDED.eligibility_score,
                        reasons=EXCLUDED.reasons,
                        evaluated_at=EXCLUDED.evaluated_at
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
    except Exception as e:
        print(f"[storage] save_results PG skipped: {e}")
    finally:
        conn.close()


def list_results(status: Optional[str] = None, app_name: Optional[str] = None,
                 level: Optional[str] = None, limit: int = 200,
                 offset: int = 0) -> List[dict]:
    conn = _try_pg_connect()
    if conn is not None:
        try:
            import psycopg2.extras
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                sql = "SELECT * FROM forecast_eligibility WHERE 1=1"
                params = []
                if status:
                    sql += " AND status=%s"; params.append(status)
                if app_name:
                    sql += " AND app_name=%s"; params.append(app_name)
                if level:
                    sql += " AND level=%s"; params.append(level)
                sql += " ORDER BY eligibility_score DESC LIMIT %s OFFSET %s"
                params += [limit, offset]
                cur.execute(sql, params)
                return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            print(f"[storage] list_results PG skipped: {e}")
            return _mem_list(status, app_name, level, limit, offset)
        finally:
            conn.close()
    return _mem_list(status, app_name, level, limit, offset)


def _mem_list(status, app_name, level, limit, offset) -> List[dict]:
    with _mem_lock:
        rows = [dict(v) for v in _mem_results.values()]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if app_name:
        rows = [r for r in rows if r["app_name"] == app_name]
    if level:
        rows = [r for r in rows if r["level"] == level]
    rows.sort(key=lambda r: r.get("eligibility_score", 0), reverse=True)
    return rows[offset:offset + limit]


def get_override(level: str, app_name: str, uri_template: str) -> Optional[dict]:
    key = _key(level, app_name, uri_template)
    with _mem_lock:
        r = _mem_results.get(key)
    if r and (r.get("override_status") or r.get("override_reason")):
        return {
            "override_status": r.get("override_status"),
            "override_reason": r.get("override_reason"),
            "override_by": r.get("override_by"),
            "override_at": r.get("override_at"),
        }
    conn = _try_pg_connect()
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT override_status, override_reason, override_by, override_at
                FROM forecast_eligibility
                WHERE level=%s AND app_name=%s AND uri_template=%s
            """, (level, app_name, uri_template))
            row = cur.fetchone()
        if row:
            return {"override_status": row[0], "override_reason": row[1],
                    "override_by": row[2], "override_at": row[3]}
    except Exception:
        return None
    finally:
        conn.close()
    return None


def apply_override(level: str, app_name: str, uri_template: str,
                   new_status: str, reason: str, operator: str,
                   change_type: str = "override") -> None:
    key = _key(level, app_name, uri_template)
    with _mem_lock:
        old = _mem_results.get(key, {})
        _mem_results[key] = {
            **old, "status": new_status, "override_status": new_status,
            "override_reason": reason, "override_by": operator,
            "override_at": datetime.now(timezone.utc).isoformat(),
        }
        _mem_history.append({
            "level": level, "app_name": app_name, "uri_template": uri_template,
            "old_status": old.get("status"), "new_status": new_status,
            "old_score": old.get("eligibility_score"),
            "new_score": old.get("eligibility_score"),
            "change_type": change_type, "operator": operator,
            "reason": reason,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        })
    conn = _try_pg_connect()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE forecast_eligibility
                SET override_status=%s, override_reason=%s, override_by=%s,
                    override_at=now(), status=%s
                WHERE level=%s AND app_name=%s AND uri_template=%s
            """, (new_status, reason, operator, new_status, level, app_name, uri_template))
            cur.execute("""
                INSERT INTO forecast_eligibility_history
                    (level, app_name, uri_template, old_status, new_status,
                     change_type, operator, reason)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """, (level, app_name, uri_template, old.get("status"),
                  new_status, change_type, operator, reason))
        conn.commit()
    except Exception as e:
        print(f"[storage] apply_override PG skipped: {e}")
    finally:
        conn.close()


def get_history(app_name: Optional[str] = None, limit: int = 100) -> List[dict]:
    conn = _try_pg_connect()
    if conn is not None:
        try:
            with conn.cursor() as cur:
                sql = "SELECT * FROM forecast_eligibility_history"
                params = []
                if app_name:
                    sql += " WHERE app_name=%s"; params.append(app_name)
                sql += " ORDER BY occurred_at DESC LIMIT %s"
                params.append(limit)
                cur.execute(sql, params)
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, r)) for r in cur.fetchall()]
        except Exception:
            pass
        finally:
            conn.close()
    with _mem_lock:
        rows = list(_mem_history)
    if app_name:
        rows = [r for r in rows if r["app_name"] == app_name]
    rows.sort(key=lambda r: r.get("occurred_at", ""), reverse=True)
    return rows[:limit]
