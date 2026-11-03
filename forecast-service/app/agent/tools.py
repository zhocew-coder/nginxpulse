"""AI Agent 工具定义与执行（阶段五，需求 §8.2）。

8 个工具：
  1. query_transaction_history      查询历史交易量
  2. evaluate_forecast_eligibility   检查应用/URL 是否适合预测
  3. list_forecastable_objects       查询可预测对象
  4. forecast_transaction_volume     执行基线或活动调整预测
  5. query_business_events           查询活动日历及相关事件
  6. compare_event_impact            活动与常规基线差分分析
  7. get_forecast_evaluation         查询历史预测准确性（回测）
  8. get_forecast_result             获取预测结果

每个工具以 OpenAPI 3.0 schema 描述参数与响应，供 OpenAI 兼容接口
function calling 使用。
"""
from __future__ import annotations

from typing import Any, Dict, List

from ..core import datasource
from ..core.config import settings
from ..eligibility import engine as elig_engine
from ..eligibility.rules import default_rules
from ..storage import eligibility_store, forecast_store, event_store
from ..forecast import engine as forecast_engine
from ..forecast import dataset as forecast_dataset
from ..forecast import event_impact
from ..forecast.backtest import rolling_backtest


# ---------------------------------------------------------------- 工具 schema

def _obj(properties: Dict, required: List[str] = None) -> Dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


TOOL_SCHEMAS: List[Dict] = [
    {
        "type": "function",
        "function": {
            "name": "query_transaction_history",
            "description": "查询指定应用/URL 的历史交易量（请求量）时序，用于了解历史规模与趋势",
            "parameters": _obj({
                "app_name": {"type": "string", "description": "应用名称"},
                "uri_template": {"type": "string", "description": "URL 模板，空表示应用级聚合", "default": ""},
                "granularity": {"type": "string", "description": "时间粒度", "enum": ["5m", "15m", "1h", "1d"], "default": "5m"},
                "days": {"type": "integer", "description": "返回最近 N 天的聚合摘要", "default": 7},
            }, ["app_name"]),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "evaluate_forecast_eligibility",
            "description": "检查某个应用或 URL 是否具备交易量预测资格，返回状态、原因与建议",
            "parameters": _obj({
                "app_name": {"type": "string", "description": "应用名称"},
                "uri_template": {"type": "string", "description": "URL 模板，空表示应用级", "default": ""},
            }, ["app_name"]),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_forecastable_objects",
            "description": "列出当前可纳入预测的对象（eligible/probation/manually_included）",
            "parameters": _obj({
                "status": {"type": "string", "description": "按状态过滤", "default": "eligible"},
                "limit": {"type": "integer", "description": "返回条数", "default": 50},
            }),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "forecast_transaction_volume",
            "description": "执行交易量预测。不传 event_id 为常规基线预测，传入则为活动调整预测",
            "parameters": _obj({
                "app_name": {"type": "string", "description": "应用名称"},
                "uri_template": {"type": "string", "description": "URL 模板", "default": ""},
                "horizon": {"type": "string", "description": "预测时长，如 24h / 7d", "default": "24h"},
                "event_id": {"type": "string", "description": "活动 ID，传入则叠加活动影响", "default": ""},
                "force": {"type": "boolean", "description": "是否强制预测不合格对象（需谨慎）", "default": False},
            }, ["app_name"]),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_business_events",
            "description": "查询活动日历中的重大活动与客户营销活动（含预热/正式/回落时间）",
            "parameters": _obj({
                "status": {"type": "string", "description": "活动状态过滤", "default": ""},
                "app_name": {"type": "string", "description": "按受影响应用过滤", "default": ""},
                "limit": {"type": "integer", "description": "返回条数", "default": 20},
            }),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_event_impact",
            "description": "分析某活动相对常规基线带来的增量、增幅、峰值变化与影响持续时间",
            "parameters": _obj({
                "app_name": {"type": "string", "description": "应用名称"},
                "uri_template": {"type": "string", "description": "URL 模板", "default": ""},
                "event_id": {"type": "string", "description": "活动 ID"},
                "horizon": {"type": "string", "description": "预测时长", "default": "24h"},
            }, ["app_name", "event_id"]),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_forecast_evaluation",
            "description": "查询模型的滚动回测指标（MAE/WAPE/sMAPE/区间覆盖率/相对基线改善）",
            "parameters": _obj({
                "app_name": {"type": "string", "description": "应用名称"},
                "uri_template": {"type": "string", "description": "URL 模板", "default": ""},
                "granularity": {"type": "string", "description": "时间粒度", "default": "5m"},
                "horizon": {"type": "string", "description": "预测时长", "default": "24h"},
                "folds": {"type": "integer", "description": "回测折数", "default": 3},
            }, ["app_name"]),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_forecast_result",
            "description": "按 forecast_id 获取已生成的预测结果完整曲线与模型信息",
            "parameters": _obj({
                "forecast_id": {"type": "string", "description": "预测任务 ID"},
            }, ["forecast_id"]),
        },
    },
]


# ---------------------------------------------------------------- 工具执行

def _summarize_history(app_name: str, uri_template: str,
                       granularity: str, days: int) -> Dict:
    s = forecast_dataset.load_series(app_name, uri_template, granularity)
    if s.empty:
        return {"error": "未找到该对象的历史数据"}
    q = forecast_dataset.quality_report(s)
    total = float(s["value"].sum())
    per_day = 86400 / {"5m": 300, "15m": 900, "1h": 3600, "1d": 86400}.get(granularity, 300)
    recent = s.tail(int(per_day * days))
    return {
        "app_name": app_name,
        "uri_template": uri_template,
        "granularity": granularity,
        "buckets": int(q["n"]),
        "total_requests": round(total, 2),
        "recent_window_requests": round(float(recent["value"].sum()), 2),
        "recent_days": days,
        "data_completeness": q["data_completeness"],
        "zero_ratio": q["zero_ratio"],
        "start": str(s["timestamp"].iloc[0]),
        "end": str(s["timestamp"].iloc[-1]),
        "data_source": "mock" if settings.use_mock else "real",
    }


def execute_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """执行工具调用，返回结果 dict（供 LLM 消费）。"""
    try:
        if name == "query_transaction_history":
            return _summarize_history(
                args["app_name"], args.get("uri_template", ""),
                args.get("granularity", "5m"), int(args.get("days", 7)))

        if name == "evaluate_forecast_eligibility":
            app = args["app_name"]
            uri = args.get("uri_template", "")
            level = "uri" if uri else "app"
            return forecast_engine.check_eligibility(level, app, uri)

        if name == "list_forecastable_objects":
            status = args.get("status", "eligible")
            rows = eligibility_store.list_results(
                status=status, limit=int(args.get("limit", 50)))
            return {
                "status": status,
                "count": len(rows),
                "objects": [
                    {"app_name": r.get("app_name"),
                     "uri_template": r.get("uri_template"),
                     "level": r.get("level"),
                     "eligibility_score": r.get("eligibility_score"),
                     "predictability": r.get("predictability"),
                     "total_requests": r.get("total_requests"),
                     "active_days": r.get("active_days")}
                    for r in rows
                ],
            }

        if name == "forecast_transaction_volume":
            event_obj = None
            eid = args.get("event_id", "")
            if eid:
                row = event_store.get_event(eid)
                if row:
                    from ..events import models as event_models
                    event_obj = event_models.BusinessEvent.from_dict(row)
            scenario = "event_adjusted" if event_obj else "baseline"
            res = forecast_engine.run_forecast(
                app_name=args["app_name"],
                uri_template=args.get("uri_template", ""),
                granularity="5m",
                horizon=args.get("horizon", "24h"),
                scenario=scenario,
                model_strategy="auto",
                force=bool(args.get("force", False)),
                event=event_obj,
            )
            if "error" in res:
                return res
            # 工具返回摘要，完整曲线用 get_forecast_result 取
            return {
                "forecast_id": res["forecast_id"],
                "scenario": scenario,
                "model": res["model"],
                "summary": res["summary"],
                "risk_flags": res.get("risk_flags", []),
                "event": (res.get("event") or {}).get("uplift_estimate"),
                "data_source": res["data_source"],
                "hint": "完整预测曲线请调用 get_forecast_result",
            }

        if name == "query_business_events":
            rows = event_store.list_events(
                status=args.get("status") or None,
                app_name=args.get("app_name") or None,
                limit=int(args.get("limit", 20)))
            events = rows if isinstance(rows, list) else rows.get("events", [])
            return {
                "count": len(events),
                "events": [
                    {"event_id": e.get("event_id"),
                     "event_name": e.get("event_name"),
                     "event_type": e.get("event_type"),
                     "start_time": e.get("start_time"),
                     "end_time": e.get("end_time"),
                     "preheat_start": e.get("preheat_start"),
                     "cooldown_end": e.get("cooldown_end"),
                     "target_apps": e.get("target_apps"),
                     "impact_level": e.get("impact_level"),
                     "expected_uplift": e.get("expected_uplift"),
                     "confidence": e.get("confidence"),
                     "status": e.get("status")}
                    for e in events
                ],
            }

        if name == "compare_event_impact":
            eid = args["event_id"]
            row = event_store.get_event(eid)
            if not row:
                return {"error": f"活动不存在：{eid}"}
            from ..events import models as event_models
            event_obj = event_models.BusinessEvent.from_dict(row)
            res = forecast_engine.run_forecast(
                app_name=args["app_name"],
                uri_template=args.get("uri_template", ""),
                granularity="5m",
                horizon=args.get("horizon", "24h"),
                scenario="event_adjusted",
                model_strategy="seasonal_naive",
                event=event_obj,
            )
            if "error" in res:
                return res
            ev = res.get("event") or {}
            return {
                "event_id": eid,
                "event_name": event_obj.event_name,
                "forecast_id": res["forecast_id"],
                "uplift_estimate": ev.get("uplift_estimate"),
                "diff_analysis": ev.get("diff_analysis"),
                "scenarios": ev.get("scenarios"),
                "summary": res["summary"],
            }

        if name == "get_forecast_evaluation":
            gran = args.get("granularity", "5m")
            s = forecast_dataset.load_series(
                args["app_name"], args.get("uri_template", ""), gran)
            if s.empty:
                return {"error": "未找到该对象的历史数据"}
            y = s["value"].to_numpy(dtype=float)
            season = forecast_dataset._season_len(gran)
            h = min(forecast_engine._horizon_buckets(
                args.get("horizon", "24h"), gran), season)
            bt = rolling_backtest(
                y, s["timestamp"], season=season, horizon=h,
                folds=int(args.get("folds", 3)),
                strategies=["seasonal_naive", "lightgbm"])
            return {"app_name": args["app_name"],
                    "granularity": gran, "backtest": bt}

        if name == "get_forecast_result":
            r = forecast_store.get_forecast(args["forecast_id"])
            if not r:
                return {"error": "预测结果不存在"}
            pts = r.get("points", [])
            return {
                "forecast_id": r.get("forecast_id"),
                "model": r.get("model"),
                "scenario": r.get("scenario"),
                "points_count": len(pts),
                "points_sample": pts[:6],
                "summary": r.get("summary"),
                "eligibility": r.get("eligibility"),
                "risk_flags": r.get("risk_flags"),
                "event": r.get("event"),
            }

        return {"error": f"未知工具：{name}"}
    except Exception as e:
        return {"error": f"{name} 执行失败：{type(e).__name__}: {e}"}
