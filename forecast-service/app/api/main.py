"""FastAPI 应用与路由。

阶段二接口（需求 §7.2~7.4）：
  POST /api/forecast/v1/eligibility/evaluate  评估单个对象
  GET  /api/forecast/v1/eligibility/list      分页查询全部对象
  POST /api/forecast/v1/eligibility/override  人工纳入/排除
  GET  /api/forecast/v1/eligibility/rules     查看准入规则
  GET  /api/forecast/v1/eligibility/history   资格变化记录
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core import datasource
from app.eligibility import engine
from app.eligibility.rules import default_rules, rules_to_dict
from app.storage import eligibility_store, forecast_store, event_store
from app.forecast import engine as forecast_engine
from app.forecast import dataset as forecast_dataset
from app.forecast.backtest import rolling_backtest
from app.agent import client as agent_client
from app.agent.tools import TOOL_SCHEMAS, execute_tool
from app.events import models as event_models
from app.events.mock_init import build_full_mock_events


def _gran_minutes(granularity: str) -> int:
    """粒度字符串转分钟数。"""
    return {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "1d": 1440}.get(granularity, 5)

app = FastAPI(
    title="NginxPulse 交易量预测服务",
    version="1.0.0",
    description="预测准入过滤、基线预测、活动影响分析",
)

# CORS：仅允许本地开发端口（禁止反射任意 Origin + credentials 组合）
_ALLOWED_ORIGINS = [
    "http://localhost:8088",
    "http://127.0.0.1:8088",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class _BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """限制请求体大小（默认 1MB），防止超大 JSON 耗尽内存。"""
    MAX_BODY = 1 * 1024 * 1024  # 1 MB

    async def dispatch(self, request: Request, call_next):
        cl = request.headers.get("content-length")
        if cl and int(cl) > self.MAX_BODY:
            return JSONResponse(
                status_code=413,
                content={"message": f"请求体过大，最大允许 {self.MAX_BODY // 1024}KB"},
            )
        return await call_next(request)


app.add_middleware(_BodySizeLimitMiddleware)


@app.on_event("startup")
def _startup():
    eligibility_store.init_schema()
    forecast_store.init_schema()
    event_store.init_schema()


# ---------------------------------------------------------------- 参数校验统一

# Pydantic 校验类型 -> 中文提示（活动接口统一以 400 + {message, errors} 返回）
_VALIDATION_MSG: Dict[str, str] = {
    "missing": "缺少必填参数",
    "datetime_parsing": "时间格式不合法，需为 ISO8601（如 2026-11-07T13:00:00+08:00）",
    "datetime_type": "时间格式不合法，需为 ISO8601（如 2026-11-07T13:00:00+08:00）",
    "date_parsing": "日期格式不合法，需为 ISO8601（如 2026-11-07）",
    "float_parsing": "数值格式不合法",
    "float_type": "数值格式不合法",
    "int_parsing": "整数格式不合法",
    "int_type": "整数格式不合法",
    "bool_parsing": "布尔值格式不合法",
    "enum": "取值不在允许范围内",
    "string_type": "文本格式不合法",
    "list_type": "需为数组",
    "greater_than_equal": "取值过小",
    "less_than_equal": "取值过大",
    "value_error": "参数取值不合法",
    "string_too_short": "文本过短",
    "string_too_long": "文本过长",
}


def _format_validation_errors(exc: RequestValidationError) -> List[str]:
    """把 Pydantic 校验错误转成中文错误列表。"""
    errors: List[str] = []
    for e in exc.errors():
        etype = str(e.get("type", ""))
        loc = [str(x) for x in e.get("loc", [])
               if str(x) not in ("query", "body", "path", "header")]
        field = loc[-1] if loc else "请求体"
        if etype == "value_error":
            raw_msg = str(e.get("msg", "参数校验失败"))
            # Pydantic 会加 "Value error, " 前缀，去掉让提示更干净
            msg = raw_msg.removeprefix("Value error, ") or "参数取值不合法"
        else:
            msg = _VALIDATION_MSG.get(etype)
            if msg is None:
                # Pydantic 的联合类型错误名带后缀（如 datetime_from_date_parsing），
                # 用子串匹配兜底，保证时间字段仍给出可操作的中文提示
                if "datetime" in etype:
                    msg = _VALIDATION_MSG["datetime_parsing"]
                elif "date" in etype:
                    msg = _VALIDATION_MSG["date_parsing"]
                elif "float" in etype or "number" in etype:
                    msg = _VALIDATION_MSG["float_parsing"]
                elif "int" in etype:
                    msg = _VALIDATION_MSG["int_parsing"]
                else:
                    msg = "参数格式不合法"
        errors.append(f"{field}：{msg}")
    return errors


@app.exception_handler(RequestValidationError)
async def _validation_exception_handler(request: Request,
                                        exc: RequestValidationError):
    """统一参数校验错误形态。

    活动相关接口统一返回 400 + {message, errors}（与业务校验一致），
    其他接口返回 422 + {message, errors}，保证中文错误信息可读。
    注意：Pydantic errors() 的 ctx 可能含不可序列化的异常对象，需清理。
    """
    errors = _format_validation_errors(exc)
    if "/events" in request.url.path:
        return JSONResponse(
            status_code=400,
            content={"detail": {"message": "活动参数校验失败",
                                "errors": errors}},
        )
    return JSONResponse(
        status_code=422,
        content={"message": "参数校验失败", "errors": errors},
    )


# ---------------------------------------------------------------- 模型

class EvaluateRequest(BaseModel):
    app_name: str
    uri_template: str = ""
    lookback_days: Optional[int] = None

    @field_validator("app_name")
    @classmethod
    def _check_app_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("app_name 不能为空")
        return v.strip()


class OverrideRequest(BaseModel):
    level: str = "uri"
    app_name: str
    uri_template: str = ""
    new_status: str
    reason: str
    operator: str = "system"

    @field_validator("app_name")
    @classmethod
    def _check_app_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("app_name 不能为空")
        return v.strip()

    @field_validator("new_status")
    @classmethod
    def _check_status(cls, v: str) -> str:
        valid = {"manually_included", "manually_excluded"}
        if v not in valid:
            raise ValueError(f"new_status 仅允许 manually_included 或 manually_excluded")
        return v


class PredictRequest(BaseModel):
    app_name: str
    uri_template: str = ""
    metric: str = "request_count"
    granularity: str = "5m"
    horizon: str = "24h"
    scenario: str = "baseline"
    model_strategy: str = "auto"
    include_interval: bool = True
    force: bool = False
    # 活动专项预测：指定活动 ID 后按 event_adjusted 叠加活动影响
    event_id: str = ""

    @field_validator("app_name")
    @classmethod
    def _check_app_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("app_name 不能为空")
        return v.strip()

    @field_validator("horizon")
    @classmethod
    def _check_horizon(cls, v: str) -> str:
        valid = {"1h", "4h", "12h", "24h", "48h", "7d", "14d", "30d"}
        if v not in valid:
            raise ValueError(f"horizon 取值不合法，允许: {', '.join(sorted(valid))}")
        return v

    @field_validator("scenario")
    @classmethod
    def _check_scenario(cls, v: str) -> str:
        valid = {"baseline", "event_adjusted"}
        if v not in valid:
            raise ValueError(f"scenario 取值不合法，允许: {', '.join(sorted(valid))}")
        return v


class EventCreateRequest(BaseModel):
    """创建/更新活动（需求 §4.2）。

    expected_uplift 允许为空：为空表示未标注增幅，
    后续活动影响计算不得编造，须按"数据不足/低置信度"处理。
    """
    event_id: Optional[str] = None            # 为空时自动生成
    event_name: str
    event_type: str = "marketing"             # marketing/batch/promotion/launch/holiday
    start_time: datetime
    end_time: datetime
    preheat_start: Optional[datetime] = None
    preheat_end: Optional[datetime] = None
    cooldown_end: Optional[datetime] = None
    target_apps: List[str] = []
    target_uris: List[str] = []               # 为空表示应用下全部 URL
    business_type: str = ""
    impact_level: str = "medium"              # low/medium/high
    expected_uplift: Optional[float] = None   # 可为空
    historical_event_id: Optional[str] = None
    event_owner: str = ""
    data_source: str = "manual"               # manual/mock/external
    confidence: Optional[str] = None          # 为空时按增幅是否标注自动推断
    status: str = "confirmed"                 # draft/confirmed/completed/cancelled


# ---------------------------------------------------------------- 评估

@app.post("/api/forecast/v1/eligibility/evaluate")
def evaluate(req: EvaluateRequest):
    """评估单个应用/URL 的预测资格。"""
    df = datasource.query_history(
        app_name=req.app_name,
        uri_template=req.uri_template or "__ALL__",
    )
    level = "uri" if req.uri_template else "app"

    if df.empty:
        raise HTTPException(status_code=404, detail="未找到该对象的时序数据")

    override = eligibility_store.get_override(level, req.app_name, req.uri_template)
    res = engine.evaluate_object(
        series=df["request_count"], timestamps=df["timestamp"],
        level=level, app_name=req.app_name, uri_template=req.uri_template,
        rules=default_rules, freq_minutes=settings.mock_bucket_minutes,
        override=override, event_included=False,
    )
    return _result_to_dict(res)


@app.get("/api/forecast/v1/eligibility/list")
def list_objects(
    status: Optional[str] = None,
    app_name: Optional[str] = None,
    level: Optional[str] = None,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    evaluate_now: bool = Query(False, description="是否实时重新评估"),
):
    """查询全部预测对象（分页/筛选）。"""
    if evaluate_now:
        _run_full_evaluation()
    return eligibility_store.list_results(
        status=status, app_name=app_name, level=level,
        limit=limit, offset=offset,
    )


@app.post("/api/forecast/v1/eligibility/override")
def override(req: OverrideRequest):
    """人工纳入/排除预测对象，记录审计日志。"""
    if req.new_status not in engine.ALL_STATUSES:
        raise HTTPException(status_code=400, detail=f"非法状态：{req.new_status}")
    eligibility_store.apply_override(
        req.level, req.app_name, req.uri_template,
        req.new_status, req.reason, req.operator,
    )
    return {"ok": True, "message": f"已将 {req.app_name}/{req.uri_template} 设为 {req.new_status}"}


@app.get("/api/forecast/v1/eligibility/rules")
def get_rules():
    """查看当前准入规则配置。"""
    return rules_to_dict(default_rules)


@app.get("/api/forecast/v1/eligibility/history")
def get_history(
    app_name: Optional[str] = None,
    limit: int = Query(100, ge=1, le=1000),
):
    """查询资格变化记录（审计）。"""
    return eligibility_store.get_history(app_name=app_name, limit=limit)


# ---------------------------------------------------------------- 全量评估

def _run_full_evaluation() -> int:
    """对所有预测对象执行全量评估并落库，返回对象数。"""
    df = datasource.get_history_series()
    objects = df.groupby(["level", "app_name", "uri_template"], dropna=False) \
        if "level" in df.columns else df.groupby(["app_name", "uri_template"])
    # mock 长表无 level 列，按 uri 是否为空推断
    results = []
    seen = set()
    for (app_name, uri_template), sub in df.groupby(["app_name", "uri_template"]):
        level = "uri" if uri_template else "app"
        key = (level, app_name, uri_template)
        if key in seen:
            continue
        seen.add(key)
        override = eligibility_store.get_override(level, app_name, uri_template)
        res = engine.evaluate_object(
            series=sub["request_count"], timestamps=sub["timestamp"],
            level=level, app_name=app_name, uri_template=uri_template,
            rules=default_rules, freq_minutes=settings.mock_bucket_minutes,
            override=override, event_included=False,
        )
        results.append(_result_to_dict(res))
    eligibility_store.save_results(results)
    return len(results)


@app.post("/api/forecast/v1/eligibility/evaluate-all")
def evaluate_all():
    """触发全量评估（开发/测试用）。"""
    n = _run_full_evaluation()
    return {"ok": True, "evaluated": n}


# ---------------------------------------------------------------- 预测

@app.post("/api/forecast/v1/predict")
def predict(req: PredictRequest):
    """创建预测任务（需求 §7.7）。

    先校验预测资格：不符合条件的对象默认拒绝常规预测并返回明确原因；
    force=true 可用于人工强制纳入/活动专项（结果保留风险标识）。

    传入 event_id 时执行活动专项预测：在常规基线上叠加活动影响增量。
    活动增幅仅来自历史实测或活动计划参数；数据不足时增量为 0 并标注，不编造。
    """
    event_obj = None
    if req.event_id:
        row = event_store.get_event(req.event_id)
        if not row:
            raise HTTPException(status_code=404,
                                detail=f"活动不存在：{req.event_id}")
        event_obj = event_models.BusinessEvent.from_dict(row)
        # 指定活动且未显式给 scenario 时，默认按活动调整预测
        if req.scenario == "baseline":
            req.scenario = "event_adjusted"

    result = forecast_engine.run_forecast(
        app_name=req.app_name,
        uri_template=req.uri_template,
        metric=req.metric,
        granularity=req.granularity,
        horizon=req.horizon,
        scenario=req.scenario,
        model_strategy=req.model_strategy,
        include_interval=req.include_interval,
        force=req.force,
        event=event_obj,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result)
    return result


@app.get("/api/forecast/v1/result/{forecast_id}")
def get_result(forecast_id: str):
    """查询预测结果：完整预测曲线、模型信息、数据质量与区间（需求 §7.8）。"""
    r = forecast_store.get_forecast(forecast_id)
    if not r:
        raise HTTPException(status_code=404, detail="预测结果不存在")
    return r


@app.get("/api/forecast/v1/evaluation")
def get_evaluation(
    app_name: str,
    uri_template: str = "",
    granularity: str = "5m",
    horizon: str = "24h",
    folds: int = 3,
    models: str = "seasonal_naive,lightgbm",
):
    """查询模型回测指标（需求 §7.9 / §6.3）。

    按时间顺序滚动回测，输出 MAE / WAPE / sMAPE / 区间覆盖率 /
    相对基线改善程度。
    """
    series = forecast_dataset.load_series(app_name, uri_template, granularity)
    if series.empty:
        raise HTTPException(status_code=404, detail="未找到该对象的历史数据")
    y = series["value"].to_numpy(dtype=float)
    season = forecast_dataset._season_len(granularity)
    h = min(forecast_engine._horizon_buckets(horizon, granularity), season)
    strategies = [s.strip() for s in models.split(",") if s.strip()]
    try:
        bt = rolling_backtest(y, series["timestamp"], season=season,
                              horizon=h, folds=folds, strategies=strategies)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"回测失败: {e}")
    return {
        "app_name": app_name,
        "uri_template": uri_template,
        "granularity": granularity,
        "horizon": horizon,
        "folds": folds,
        "backtest": bt,
    }


@app.get("/api/forecast/v1/forecasts")
def list_forecasts(app_name: Optional[str] = None, limit: int = 50):
    """列出历史预测记录。"""
    return forecast_store.list_forecasts(app_name=app_name, limit=limit)


@app.get("/api/forecast/v1/history")
def get_history_series(
    app_name: str,
    uri_template: str = "",
    granularity: str = "5m",
    hours: int = Query(24, ge=1, le=720),
):
    """查询实际交易量历史时序（用于前端图表"实际值"曲线）。

    返回最近 N 小时的实际请求量数据点。
    """
    series = forecast_dataset.load_series(app_name, uri_template, granularity)
    if series.empty:
        raise HTTPException(status_code=404, detail="未找到该对象的历史数据")
    season = forecast_dataset._season_len(granularity)
    buckets = int(hours * 60 / _gran_minutes(granularity))
    tail = series.tail(buckets)
    return {
        "app_name": app_name,
        "uri_template": uri_template,
        "granularity": granularity,
        "hours": hours,
        "count": len(tail),
        "data_source": settings.use_mock and "mock" or "real",
        "points": [
            {"timestamp": str(row["timestamp"]), "actual": float(row["value"])}
            for _, row in tail.iterrows()
        ],
    }


# ---------------------------------------------------------------- 活动日历（需求 §4.2）

@app.post("/api/forecast/v1/events")
def create_event(req: EventCreateRequest):
    """创建活动。

    校验：start_time 必须早于 end_time；target_apps 不能为空；
    预热期/回落期与正式期时间顺序必须合理。
    """
    event_id = (req.event_id or "").strip() or event_models.make_event_id()
    # 置信度未指定时推断：未标注增幅 -> low；已标注 -> medium
    confidence = req.confidence or ("medium" if req.expected_uplift is not None else "low")
    event = event_models.BusinessEvent(
        event_id=event_id,
        event_name=req.event_name,
        event_type=req.event_type,
        start_time=req.start_time,
        end_time=req.end_time,
        preheat_start=req.preheat_start,
        preheat_end=req.preheat_end,
        cooldown_end=req.cooldown_end,
        target_apps=list(req.target_apps),
        target_uris=list(req.target_uris),
        business_type=req.business_type,
        impact_level=req.impact_level,
        expected_uplift=req.expected_uplift,
        historical_event_id=req.historical_event_id,
        event_owner=req.event_owner,
        data_source=req.data_source,
        confidence=confidence,
        status=req.status,
    )
    errors = event_models.validate_event(event)
    if errors:
        raise HTTPException(status_code=400, detail={"message": "活动参数校验失败",
                                                     "errors": errors})
    event = event_models.normalize_event(event)
    saved = event_store.save_event(event.to_dict(), operator=req.event_owner or "system")
    return {"ok": True, "message": f"活动 {event_id} 已保存", "event": saved}


@app.get("/api/forecast/v1/events")
def list_events(
    status: Optional[str] = None,
    app_name: Optional[str] = None,
    start_from: Optional[datetime] = None,
    start_to: Optional[datetime] = None,
    event_type: Optional[str] = None,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """查询活动列表，支持按状态、应用、开始时间范围、类型筛选。"""
    total = event_store.count_events(
        status=status, app_name=app_name,
        start_from=start_from.isoformat() if start_from else None,
        start_to=start_to.isoformat() if start_to else None,
        event_type=event_type,
    )
    rows = event_store.list_events(
        status=status, app_name=app_name,
        start_from=start_from.isoformat() if start_from else None,
        start_to=start_to.isoformat() if start_to else None,
        event_type=event_type, limit=limit, offset=offset,
    )
    return {"total": total, "count": len(rows), "offset": offset, "events": rows}


@app.post("/api/forecast/v1/events/init-mock")
def init_mock_events():
    """初始化 mock 活动数据（双十一营销 / 月末批量清算 / 消费信贷推广）。"""
    events = build_full_mock_events()
    saved = []
    for ev in events:
        errors = event_models.validate_event(ev)
        if errors:
            # mock 数据本身不应非法；出现问题时跳过并提示，避免污染库
            print(f"[events] mock 活动 {ev.event_id} 校验失败，已跳过：{errors}")
            continue
        saved.append(event_store.save_event(ev.to_dict(), operator="mock-init"))
    return {
        "ok": True,
        "message": f"已初始化 {len(saved)} 个 mock 活动",
        "count": len(saved),
        "events": saved,
    }


@app.get("/api/forecast/v1/events/{event_id}")
def get_event(event_id: str):
    """查询单个活动。"""
    row = event_store.get_event(event_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"活动不存在：{event_id}")
    return row


@app.get("/api/forecast/v1/events/{event_id}/phase")
def get_event_phase(event_id: str, ts: Optional[datetime] = None):
    """查询活动在指定时间点（默认当前时间）所处的阶段。

    阶段：preheat 预热期 / active 正式期 / cooldown 回落期 / none 不受影响。
    同时返回该阶段可用增幅；增幅未标注时返回 null 并附说明（不编造）。
    """
    row = event_store.get_event(event_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"活动不存在：{event_id}")
    event = event_models.BusinessEvent.from_dict(row)
    point = ts or datetime.now(event_models.TZ)
    # 阶段判定统一走 BusinessEvent 方法（缺口1）
    phase = event.phase_of(point)
    uplift, note = event_models.resolve_phase_uplift(event, phase, point)
    return {
        "event_id": event_id,
        "ts": point.isoformat(),
        "phase": phase,
        "phase_label": event_models.PHASE_LABELS.get(phase, phase),
        "uplift": uplift,
        "note": note,
        "confidence": event.confidence,
    }


@app.delete("/api/forecast/v1/events/{event_id}")
def delete_event(event_id: str):
    """删除活动。"""
    existed = event_store.delete_event(event_id)
    if not existed:
        raise HTTPException(status_code=404, detail=f"活动不存在：{event_id}")
    return {"ok": True, "message": f"活动 {event_id} 已删除"}


def _result_to_dict(res: engine.EligibilityResult) -> dict:
    # 把 features 摊平到顶层，保证落库层能直接访问各特征列
    out = {
        "level": res.level,
        "app_name": res.app_name,
        "uri_template": res.uri_template,
        "status": res.status,
        "history_days": res.history_days,
        "total_requests": res.total_requests,
        "active_days": res.active_days,
        "data_completeness": res.data_completeness,
        "eligibility_score": res.eligibility_score,
        "predictability": res.predictability,
        "reasons": res.reasons,
        "features": res.features,
        "override_status": res.override_status,
        "override_reason": res.override_reason,
        "override_by": res.override_by,
        "override_at": res.override_at,
        "event_included": res.event_included,
        "event_confidence": res.event_confidence,
    }
    for k, v in (res.features or {}).items():
        out.setdefault(k, v)
    out.setdefault("config_version", "v1")
    out.setdefault("data_source", "mock")
    return out


# ---------------------------------------------------------------- AI Agent（阶段五）

class AgentChatRequest(BaseModel):
    question: str

    @field_validator("question")
    @classmethod
    def _check_question(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("question 不能为空")
        if len(v) > 10000:
            raise ValueError("question 过长，最大 10000 字符")
        return v
    tool_call_enabled: bool = True


@app.post("/api/forecast/v1/agent/chat")
def agent_chat(req: AgentChatRequest):
    """自然语言问答：自动编排预测工具并解释结果（需求 §8.3）。

    所有预测数字均由算法引擎产出，模型只负责编排与解释。
    """
    return agent_client.run_agent(
        req.question, tool_call_enabled=req.tool_call_enabled)


@app.get("/api/forecast/v1/agent/tools")
def agent_tools():
    """列出 Agent 可用工具（OpenAI function calling schema）。"""
    return {
        "count": len(TOOL_SCHEMAS),
        "tools": [t["function"]["name"] for t in TOOL_SCHEMAS],
        "schemas": TOOL_SCHEMAS,
    }


@app.get("/api/forecast/v1/agent/config")
def agent_config():
    """查看 LLM 配置（**已脱敏**，不含真实 API Key）。"""
    return agent_client.load_llm_config().safe_dict()


@app.post("/api/forecast/v1/agent/tool/execute")
def agent_tool_execute(payload: dict):
    """直接执行单个工具（调试用），payload: {name, args}。"""
    return execute_tool(payload.get("name", ""), payload.get("args", {}))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.host, port=settings.port)
