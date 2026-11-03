"""活动（业务事件）存储层。

双模式（与 eligibility_store 保持一致）：
- 真实 PG 可用时落库（生产/联调）
- PG 不可用时内存后备（mock 开发验证，进程内持久）

写操作先写内存再写 PG，PG 异常仅打印不抛出，保证接口可用。
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from ..core.config import settings

# 项目统一使用东八区（与 mock 生成器、活动模型保持一致）
TZ = timezone(timedelta(hours=8))


# ---------------- 内存后备存储 ----------------
_mem_lock = threading.Lock()
_mem_events: Dict[str, dict] = {}   # event_id -> 活动字典
_mem_history: List[dict] = []       # 活动变更审计
_schema_ready = False


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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_history(event_id: str, action: str, operator: str,
                    snapshot: Optional[dict] = None) -> None:
    """记录内存审计日志（PG 模式下同时写 forecast_events_history）。"""
    _mem_history.append({
        "event_id": event_id,
        "action": action,
        "operator": operator,
        "snapshot": json.dumps(snapshot or {}, ensure_ascii=False, default=str),
        "occurred_at": _now_iso(),
    })


def _row_to_dict(row: dict) -> dict:
    """PG 行转字典：datetime / 数组统一成可 JSON 序列化的形式。"""
    out = {}
    for k, v in row.items():
        if k == "id":
            continue  # 内部代理主键，不对外暴露（内存模式无此字段，保持两模式一致）
        if isinstance(v, datetime):
            # 统一按东八区输出，与内存模式（BusinessEvent.to_dict）保持一致
            out[k] = v.astimezone(TZ).isoformat()
        elif isinstance(v, list):
            out[k] = list(v)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------- 建表

def init_schema() -> None:
    """建表（PG 可用时）。内存模式跳过。"""
    global _schema_ready
    conn = _try_pg_connect()
    if conn is None:
        _schema_ready = True  # 内存模式
        return
    try:
        sql_path = Path(__file__).resolve().parents[2] / "sql" / "003_events.sql"
        with conn.cursor() as cur:
            with open(sql_path, encoding="utf-8") as f:
                cur.execute(f.read())
        conn.commit()
        _schema_ready = True
    except Exception as e:
        print(f"[storage] events init_schema skipped: {e}")
        _schema_ready = True
    finally:
        conn.close()


# ---------------------------------------------------------------- 写

_INSERT_SQL = """
    INSERT INTO forecast_events
        (event_id, event_name, event_type, start_time, end_time,
         preheat_start, preheat_end, cooldown_end, target_apps, target_uris,
         business_type, impact_level, expected_uplift, historical_event_id,
         event_owner, data_source, confidence, status, updated_at)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
    ON CONFLICT (event_id) DO UPDATE SET
        event_name=EXCLUDED.event_name,
        event_type=EXCLUDED.event_type,
        start_time=EXCLUDED.start_time,
        end_time=EXCLUDED.end_time,
        preheat_start=EXCLUDED.preheat_start,
        preheat_end=EXCLUDED.preheat_end,
        cooldown_end=EXCLUDED.cooldown_end,
        target_apps=EXCLUDED.target_apps,
        target_uris=EXCLUDED.target_uris,
        business_type=EXCLUDED.business_type,
        impact_level=EXCLUDED.impact_level,
        expected_uplift=EXCLUDED.expected_uplift,
        historical_event_id=EXCLUDED.historical_event_id,
        event_owner=EXCLUDED.event_owner,
        data_source=EXCLUDED.data_source,
        confidence=EXCLUDED.confidence,
        status=EXCLUDED.status,
        updated_at=now()
"""


def save_event(event: dict, operator: str = "system") -> dict:
    """保存 / 更新单个活动（按 event_id 幂等覆盖）。

    Args:
        event: 活动字典（BusinessEvent.to_dict() 的输出）
        operator: 操作人，用于审计

    Returns:
        保存后的活动字典
    """
    row = dict(event)
    if not row.get("event_id"):
        raise ValueError("保存活动失败：event_id 不能为空")
    row.setdefault("data_source", "manual")
    row.setdefault("confidence", "low")
    row.setdefault("status", "draft")
    row.setdefault("target_apps", [])
    row.setdefault("target_uris", [])

    action = "update"
    with _mem_lock:
        action = "update" if row["event_id"] in _mem_events else "create"
        _mem_events[row["event_id"]] = dict(row)
        _append_history(row["event_id"], action, operator, row)

    conn = _try_pg_connect()
    if conn is None:
        return row
    try:
        import psycopg2.extras
        with conn.cursor() as cur:
            cur.execute(_INSERT_SQL, (
                row["event_id"], row["event_name"], row["event_type"],
                row.get("start_time"), row.get("end_time"),
                row.get("preheat_start"), row.get("preheat_end"),
                row.get("cooldown_end"),
                list(row.get("target_apps") or []),
                list(row.get("target_uris") or []),
                row.get("business_type", ""), row.get("impact_level", "medium"),
                row.get("expected_uplift", None), row.get("historical_event_id", None),
                row.get("event_owner", ""), row.get("data_source", "manual"),
                row.get("confidence", "low"), row.get("status", "draft"),
            ))
            cur.execute("""
                INSERT INTO forecast_events_history (event_id, action, operator, snapshot)
                VALUES (%s,%s,%s,%s)
            """, (row["event_id"], action, operator, psycopg2.extras.Json(row)))
        conn.commit()
    except Exception as e:
        print(f"[storage] save_event PG skipped: {e}")
    finally:
        conn.close()
    return row


def delete_event(event_id: str, operator: str = "system") -> bool:
    """删除活动，返回是否存在过该活动。"""
    existed = False
    snapshot = None
    with _mem_lock:
        if event_id in _mem_events:
            existed = True
            snapshot = _mem_events.pop(event_id)
            _append_history(event_id, "delete", operator, snapshot)

    conn = _try_pg_connect()
    if conn is None:
        return existed
    try:
        import psycopg2.extras
        with conn.cursor() as cur:
            cur.execute("SELECT event_id FROM forecast_events WHERE event_id=%s",
                        (event_id,))
            existed = existed or cur.fetchone() is not None
            cur.execute("DELETE FROM forecast_events WHERE event_id=%s", (event_id,))
            if existed:
                # 仅对真实发生的删除记录审计，避免 404 删除写入脏日志
                cur.execute("""
                    INSERT INTO forecast_events_history (event_id, action, operator, snapshot)
                    VALUES (%s,%s,%s,%s)
                """, (event_id, "delete", operator,
                      psycopg2.extras.Json(snapshot or {"event_id": event_id})))
        conn.commit()
    except Exception as e:
        print(f"[storage] delete_event PG skipped: {e}")
    finally:
        conn.close()
    return existed


# ---------------------------------------------------------------- 读

def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    """把 ISO 字符串解析为 datetime（用于内存模式的时间范围筛选）。"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _match_filters(row: dict, status: Optional[str], app_name: Optional[str],
                   start_from: Optional[str], start_to: Optional[str]) -> bool:
    """内存模式的筛选逻辑。"""
    if status and row.get("status") != status:
        return False
    if app_name and app_name not in (row.get("target_apps") or []):
        return False
    st = _parse_dt(row.get("start_time"))
    if st is not None:
        if start_from:
            f = _parse_dt(start_from)
            if f is not None and st < f:
                return False
        if start_to:
            t = _parse_dt(start_to)
            if t is not None and st > t:
                return False
    return True


def list_events(status: Optional[str] = None, app_name: Optional[str] = None,
                start_from: Optional[str] = None, start_to: Optional[str] = None,
                event_type: Optional[str] = None,
                limit: int = 200, offset: int = 0) -> List[dict]:
    """查询活动列表，支持按状态、应用、开始时间范围、类型筛选。"""
    conn = _try_pg_connect()
    if conn is not None:
        try:
            import psycopg2.extras
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                sql = "SELECT * FROM forecast_events WHERE 1=1"
                params: List[object] = []
                if status:
                    sql += " AND status=%s"
                    params.append(status)
                if app_name:
                    sql += " AND %s = ANY(target_apps)"
                    params.append(app_name)
                if event_type:
                    sql += " AND event_type=%s"
                    params.append(event_type)
                if start_from:
                    sql += " AND start_time >= %s"
                    params.append(start_from)
                if start_to:
                    sql += " AND start_time <= %s"
                    params.append(start_to)
                sql += " ORDER BY start_time DESC LIMIT %s OFFSET %s"
                params += [limit, offset]
                cur.execute(sql, params)
                return [_row_to_dict(dict(r)) for r in cur.fetchall()]
        except Exception as e:
            print(f"[storage] list_events PG skipped: {e}")
            return _mem_list(status, app_name, start_from, start_to,
                             event_type, limit, offset)
        finally:
            conn.close()
    return _mem_list(status, app_name, start_from, start_to, event_type, limit, offset)


def count_events(status: Optional[str] = None, app_name: Optional[str] = None,
                 start_from: Optional[str] = None, start_to: Optional[str] = None,
                 event_type: Optional[str] = None) -> int:
    """统计满足筛选条件的活动数量（分页总数用）。"""
    conn = _try_pg_connect()
    if conn is not None:
        try:
            with conn.cursor() as cur:
                sql = "SELECT COUNT(*) FROM forecast_events WHERE 1=1"
                params: List[object] = []
                if status:
                    sql += " AND status=%s"
                    params.append(status)
                if app_name:
                    sql += " AND %s = ANY(target_apps)"
                    params.append(app_name)
                if event_type:
                    sql += " AND event_type=%s"
                    params.append(event_type)
                if start_from:
                    sql += " AND start_time >= %s"
                    params.append(start_from)
                if start_to:
                    sql += " AND start_time <= %s"
                    params.append(start_to)
                cur.execute(sql, params)
                return int(cur.fetchone()[0])
        except Exception as e:
            print(f"[storage] count_events PG skipped: {e}")
            return len(_mem_list(status, app_name, start_from, start_to,
                                 event_type, 100000, 0))
        finally:
            conn.close()
    return len(_mem_list(status, app_name, start_from, start_to, event_type, 100000, 0))


def _mem_list(status, app_name, start_from, start_to, event_type,
              limit: int, offset: int) -> List[dict]:
    with _mem_lock:
        rows = [dict(v) for v in _mem_events.values()]
    rows = [r for r in rows
            if _match_filters(r, status, app_name, start_from, start_to)]
    if event_type:
        rows = [r for r in rows if r.get("event_type") == event_type]
    rows.sort(key=lambda r: str(r.get("start_time") or ""), reverse=True)
    return rows[offset:offset + limit]


def get_event(event_id: str) -> Optional[dict]:
    """按 event_id 查询单个活动，不存在返回 None。"""
    with _mem_lock:
        row = _mem_events.get(event_id)
    if row is not None:
        return dict(row)

    conn = _try_pg_connect()
    if conn is None:
        return None
    try:
        import psycopg2.extras
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM forecast_events WHERE event_id=%s", (event_id,))
            r = cur.fetchone()
        return _row_to_dict(dict(r)) if r else None
    except Exception as e:
        print(f"[storage] get_event PG skipped: {e}")
        return None
    finally:
        conn.close()


def get_history(event_id: Optional[str] = None, limit: int = 100) -> List[dict]:
    """查询活动变更审计记录。"""
    conn = _try_pg_connect()
    if conn is not None:
        try:
            with conn.cursor() as cur:
                sql = "SELECT * FROM forecast_events_history"
                params: List[object] = []
                if event_id:
                    sql += " WHERE event_id=%s"
                    params.append(event_id)
                sql += " ORDER BY occurred_at DESC LIMIT %s"
                params.append(limit)
                cur.execute(sql, params)
                cols = [d[0] for d in cur.description]
                return [_row_to_dict(dict(zip(cols, r))) for r in cur.fetchall()]
        except Exception as e:
            print(f"[storage] events get_history PG skipped: {e}")
        finally:
            conn.close()
    with _mem_lock:
        rows = list(_mem_history)
    if event_id:
        rows = [r for r in rows if r["event_id"] == event_id]
    rows.sort(key=lambda r: r.get("occurred_at", ""), reverse=True)
    return rows[:limit]
