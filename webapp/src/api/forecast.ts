/**
 * 交易量预测服务 API 封装（阶段二：预测对象管理）。
 *
 * 后端为独立的 Python FastAPI 服务，与 Go 主服务分开部署。
 * 开发环境前端直连 http://localhost:8090，生产环境可通过
 * Vite 环境变量 VITE_FORECAST_API_BASE_URL 覆盖（需以 /api/forecast/v1 结尾）。
 */
import axios from 'axios';

/** 预测服务默认基础地址（开发环境直连宿主机 8090 端口） */
export const DEFAULT_FORECAST_BASE_URL = 'http://localhost:8090/api/forecast/v1';

/** 全量评估较慢，单独放宽超时时间（毫秒） */
const EVALUATE_ALL_TIMEOUT = 180000;

/** 普通接口超时时间（毫秒） */
const REQUEST_TIMEOUT = 30000;

/** 对象层级：应用级汇总 / 接口级 */
export type ForecastLevel = 'app' | 'uri';

/** 预测资格状态 */
export type EligibilityStatus =
  | 'eligible'
  | 'probation'
  | 'cold'
  | 'insufficient_history'
  | 'poor_data_quality'
  | 'low_predictability'
  | 'manually_included'
  | 'manually_excluded';

/** 可预测性档位 */
export type PredictabilityBand = 'high' | 'medium' | 'low' | 'none';

/** 资格变化类型 */
export type EligibilityChangeType = 'override' | 'evaluate' | string;

/** 预测对象（GET /eligibility/list 的单条记录） */
export interface ForecastEligibilityObject {
  id?: number | string;
  /** 对象层级：app=应用级汇总，uri=接口级 */
  level: ForecastLevel;
  /** 应用名称 */
  app_name: string;
  /** URI 模板，应用级对象为空字符串 */
  uri_template: string;
  /** 观察窗口内交易总量 */
  total_requests: number;
  /** 有交易的活跃天数 */
  active_days: number;
  /** 活跃天数占比（0-1） */
  active_day_ratio: number;
  /** 非零时间桶数量 */
  nonzero_buckets: number;
  /** 非零时间桶占比（0-1） */
  nonzero_bucket_ratio: number;
  /** 数据完整率（0-1） */
  data_completeness: number;
  /** 日均交易量 */
  avg_daily_requests: number;
  /** 单日峰值交易量 */
  max_daily_requests: number;
  /** 平均请求间隔（分钟） */
  avg_interarrival_minutes: number;
  /** 周周期强度（0-1） */
  weekly_seasonality_score: number;
  /** 月周期强度（0-1） */
  monthly_seasonality_score: number;
  /** 历史覆盖天数 */
  history_days: number;
  /** 准入评估结果状态 */
  status: EligibilityStatus;
  /** 可预测性档位 */
  predictability: PredictabilityBand;
  /** 资格评分（0-100） */
  eligibility_score: number;
  /** 判定原因（中文说明数组） */
  reasons: string[];
  /** 时间桶总数 */
  bucket_count: number;
  /** 缺失时间桶数量 */
  missing_buckets: number;
  /** 夜间集中度（0-1） */
  night_concentration: number;
  /** 人工覆盖状态（无覆盖时为空字符串或 null） */
  override_status: string | null;
  /** 人工覆盖原因 */
  override_reason: string | null;
  /** 人工覆盖操作人 */
  override_by: string | null;
  /** 人工覆盖时间（ISO 字符串） */
  override_at: string | null;
  /** 是否纳入活动事件因子 */
  event_included: boolean;
  /** 事件置信度（0-1） */
  event_confidence: number;
  /** 数据来源：mock / real */
  data_source: string;
  /** 最近评估时间（ISO 字符串） */
  evaluated_at: string;
}

/** 列表查询参数（GET /eligibility/list） */
export interface EligibilityListParams {
  status?: EligibilityStatus | string;
  app_name?: string;
  level?: ForecastLevel | string;
  limit?: number;
  offset?: number;
}

/** 人工覆盖请求体（POST /eligibility/override） */
export interface EligibilityOverridePayload {
  level: ForecastLevel | string;
  app_name: string;
  uri_template: string;
  new_status: EligibilityStatus | string;
  reason: string;
  operator: string;
}

/** 人工覆盖响应 */
export interface EligibilityOverrideResult {
  ok: boolean;
  message: string;
}

/** 全量评估响应（POST /eligibility/evaluate-all） */
export interface EvaluateAllResult {
  ok: boolean;
  evaluated: number;
}

/** 准入规则配置（GET /eligibility/rules） */
export interface EligibilityRules {
  /** 观察窗口（天） */
  lookback_days: number;
  /** 视为历史充分的最小天数 */
  min_history_days_full: number;
  /** 视为历史不足的最小天数 */
  min_history_days_min: number;
  /** 数据完整率下限（0-1） */
  min_completeness: number;
  /** 进入进一步评估的请求量下限 */
  min_total_requests_eligible: number;
  /** 进入进一步评估的活跃天数下限 */
  min_active_days_eligible: number;
  /** 冷系统请求量上限 */
  cold_total_requests: number;
  /** 冷系统活跃天数上限 */
  cold_active_days: number;
  /** 观察期请求量上限 */
  probation_total_requests: number;
  /** 观察期活跃天数上限 */
  probation_active_days: number;
  /** 周期性自相关阈值（0-1） */
  seasonality_acf_threshold: number;
  /** 批处理夜间集中度阈值（0-1） */
  batch_concentration_threshold: number;
  /** 资格评分权重（各维度权重之和为 1） */
  score_weights: Record<string, number>;
  /** 可预测性分档（[下界, 档位] 列表） */
  predictability_bands: Array<{ min: number; label: string }>;
  /** 后端可能返回的其它扩展字段 */
  [key: string]: unknown;
}

/** 资格变化记录（GET /eligibility/history） */
export interface EligibilityHistoryRecord {
  id?: number | string;
  level: ForecastLevel | string;
  app_name: string;
  uri_template: string;
  old_status: string | null;
  new_status: string | null;
  old_score?: number | null;
  new_score?: number | null;
  change_type: EligibilityChangeType;
  operator: string | null;
  reason: string | null;
  occurred_at: string;
}

/** 单个对象评估请求体（POST /eligibility/evaluate） */
export interface EvaluateSinglePayload {
  app_name: string;
  uri_template?: string;
  lookback_days?: number;
}

/**
 * 解析预测服务基础地址。
 * 优先使用构建期注入的 VITE_FORECAST_API_BASE_URL，否则回退到默认地址。
 */
function resolveBaseUrl(): string {
  const raw = String(import.meta.env?.VITE_FORECAST_API_BASE_URL || '').trim();
  return raw || DEFAULT_FORECAST_BASE_URL;
}

/** 当前生效的预测服务基础地址 */
export const FORECAST_API_BASE_URL = resolveBaseUrl();

/** 预测服务专用 axios 实例（与主服务 client 隔离，避免访问密钥/代理混淆） */
const forecastClient = axios.create({
  baseURL: FORECAST_API_BASE_URL,
  timeout: REQUEST_TIMEOUT,
  headers: {
    'X-Requested-With': 'XMLHttpRequest',
  },
});

/**
 * 提取接口错误信息，统一成可读中文/原始 message。
 * @param error 任意异常对象
 * @param fallback 兜底提示文案
 */
function extractErrorMessage(error: unknown, fallback: string): string {
  const axiosError = error as { response?: { data?: unknown }; message?: string };
  const data = axiosError?.response?.data as { detail?: unknown; error?: unknown; message?: unknown } | undefined;
  if (data && typeof data === 'object') {
    const detail = data.detail ?? data.error ?? data.message;
    if (typeof detail === 'string' && detail.trim()) {
      return detail;
    }
  }
  if (axiosError?.message) {
    return axiosError.message;
  }
  return fallback;
}

/**
 * 把后端返回值统一规范化为数组。
 * 后端当前直接返回数组，这里兼容未来可能改为 { items } / { data } 包裹的情况。
 */
function normalizeArray<T>(payload: unknown): T[] {
  if (Array.isArray(payload)) {
    return payload as T[];
  }
  if (payload && typeof payload === 'object') {
    const wrapper = payload as { items?: unknown; data?: unknown; results?: unknown };
    if (Array.isArray(wrapper.items)) {
      return wrapper.items as T[];
    }
    if (Array.isArray(wrapper.data)) {
      return wrapper.data as T[];
    }
    if (Array.isArray(wrapper.results)) {
      return wrapper.results as T[];
    }
  }
  return [];
}

/**
 * 构造列表查询串，跳过空值参数。
 * @param params 列表查询参数
 */
function buildListParams(params: EligibilityListParams = {}): Record<string, string> {
  const query: Record<string, string> = {};
  Object.keys(params).forEach((key) => {
    const value = (params as Record<string, unknown>)[key];
    if (value !== undefined && value !== null && value !== '') {
      query[key] = String(value);
    }
  });
  return query;
}

/**
 * 查询预测对象列表。
 * @param params 状态 / 应用名 / 层级 / 分页参数
 */
export const fetchEligibilityList = async (
  params: EligibilityListParams = {}
): Promise<ForecastEligibilityObject[]> => {
  try {
    const response = await forecastClient.get<unknown>('eligibility/list', {
      params: buildListParams(params),
    });
    return normalizeArray<ForecastEligibilityObject>(response.data);
  } catch (error) {
    throw new Error(extractErrorMessage(error, '获取预测对象列表失败'));
  }
};

/**
 * 触发全量资格评估（耗时较长，已放宽超时）。
 */
export const evaluateAllEligibility = async (): Promise<EvaluateAllResult> => {
  try {
    const response = await forecastClient.post<EvaluateAllResult>(
      'eligibility/evaluate-all',
      null,
      { timeout: EVALUATE_ALL_TIMEOUT }
    );
    const raw = (response.data || {}) as Partial<EvaluateAllResult>;
    return {
      ok: raw.ok !== false,
      evaluated: Number(raw.evaluated ?? 0),
    };
  } catch (error) {
    throw new Error(extractErrorMessage(error, '全量评估失败'));
  }
};

/**
 * 人工纳入 / 排除预测对象。
 * @param payload 覆盖请求体（含原因与操作人，写入审计记录）
 */
export const overrideEligibility = async (
  payload: EligibilityOverridePayload
): Promise<EligibilityOverrideResult> => {
  try {
    const response = await forecastClient.post<unknown>('eligibility/override', payload);
    const raw = (response.data || {}) as Partial<EligibilityOverrideResult>;
    return {
      ok: raw.ok !== false,
      message: raw.message || '操作已提交',
    };
  } catch (error) {
    throw new Error(extractErrorMessage(error, '提交人工操作失败'));
  }
};

/**
 * 查询准入规则配置。
 */
export const fetchEligibilityRules = async (): Promise<EligibilityRules> => {
  try {
    const response = await forecastClient.get<unknown>('eligibility/rules');
    const raw = (response.data || {}) as EligibilityRules;
    return {
      ...raw,
      score_weights: raw.score_weights && typeof raw.score_weights === 'object' ? raw.score_weights : {},
      predictability_bands: Array.isArray(raw.predictability_bands) ? raw.predictability_bands : [],
    };
  } catch (error) {
    throw new Error(extractErrorMessage(error, '获取准入规则失败'));
  }
};

/**
 * 查询资格变化记录（审计）。
 * @param appName 可选，按应用名过滤
 * @param limit 返回条数，默认 100
 */
export const fetchEligibilityHistory = async (
  appName?: string,
  limit = 100
): Promise<EligibilityHistoryRecord[]> => {
  try {
    const response = await forecastClient.get<unknown>('eligibility/history', {
      params: buildListParams({ app_name: appName, limit }),
    });
    return normalizeArray<EligibilityHistoryRecord>(response.data);
  } catch (error) {
    throw new Error(extractErrorMessage(error, '获取资格变化记录失败'));
  }
};

/**
 * 评估单个预测对象。
 * @param payload 应用名与 URI 模板（URI 为空表示应用级汇总）
 */
export const evaluateSingleEligibility = async (
  payload: EvaluateSinglePayload
): Promise<ForecastEligibilityObject> => {
  try {
    const response = await forecastClient.post<unknown>('eligibility/evaluate', {
      app_name: payload.app_name,
      uri_template: payload.uri_template || '',
      lookback_days: payload.lookback_days,
    });
    const raw = (response.data || {}) as ForecastEligibilityObject;
    return raw;
  } catch (error) {
    throw new Error(extractErrorMessage(error, '评估该对象失败'));
  }
};

/* ================================================================
 * 阶段六：交易量预测图表（预测总览 / 活动影响分析）
 * ================================================================ */

/** 预测模型拟合耗时较长，单独放宽超时时间（毫秒） */
const PREDICT_TIMEOUT = 60000;

/** 预测时间点（POST /predict 的 points 单条） */
export interface ForecastPoint {
  /** 时间戳（ISO8601，带时区） */
  timestamp: string;
  /** 常规基线预测值 */
  baseline_forecast: number;
  /** 活动影响增量 */
  event_increment: number;
  /** 活动调整后预测值 */
  event_adjusted_forecast: number;
  /** 区间下界 */
  lower_bound: number;
  /** 区间上界 */
  upper_bound: number;
  /** 平均 QPS */
  avg_qps: number;
  /** 峰值 QPS（5m 聚合无法得到真实瞬时峰值，常为 null） */
  peak_qps: number | null;
  /** 活动阶段（活动调整场景下由后端填充）：preheat / active / cooldown / none */
  event_phase?: string;
}

/** 预测摘要（POST /predict 的 summary） */
export interface ForecastSummary {
  total_baseline: number;
  total_event_adjusted: number;
  total_event_increment: number;
  peak_baseline: number;
  peak_event_adjusted: number;
  peak_timestamp: string;
  peak_qps: number | null;
  avg_qps: number;
}

/** 差分分析方法一：活动期 vs 常规基线 */
export interface ForecastDiffMethod1 {
  total_baseline: number;
  total_event_adjusted: number;
  total_increment: number;
  uplift_ratio: number | null;
  peak_baseline: number;
  peak_adjusted: number;
  peak_increment: number;
  peak_time_baseline: string;
  peak_time_adjusted: string;
  impact_duration_points: number;
}

/** 差分分析方法二：历史同期对比 */
export interface ForecastDiffMethod2 {
  available: boolean;
  note?: string;
  current_event_total?: number;
  baseline_total?: number;
  yoy_growth?: number | null;
  reason?: string;
}

/** 差分分析方法三：活动前后对比 */
export interface ForecastDiffMethod3 {
  pre_event_baseline: number | null;
  preheat_avg: number | null;
  active_avg: number | null;
  cooldown_avg: number | null;
  preheat_growth_vs_baseline: number | null;
  active_growth_vs_baseline: number | null;
  cooldown_decay_rate: number | null;
  note: string;
}

/** 差分分析方法四：DID 双差分 */
export interface ForecastDiffMethod4 {
  available: boolean;
  reason?: string;
  treated_increment?: number;
  control_increment?: number;
  did_net_effect?: number;
  note?: string;
}

/** 四种差分分析汇总 */
export interface ForecastDiffAnalysis {
  method1_vs_baseline: ForecastDiffMethod1;
  method2_historical_same_period: ForecastDiffMethod2;
  method3_before_after: ForecastDiffMethod3;
  method4_did: ForecastDiffMethod4;
}

/** 活动增幅估计（来自历史实测或活动计划参数，数据不足时 uplift 为 null） */
export interface ForecastUpliftEstimate {
  uplift: number | null;
  source: string;
  confidence: string;
}

/** 单情景对比结果 */
export interface ForecastScenarioItem {
  factor: number;
  total: number;
  increment: number;
}

/** 保守 / 基准 / 乐观三情景对比 */
export interface ForecastScenarios {
  available: boolean;
  reason?: string;
  uplift?: number | null;
  scenarios: Record<string, ForecastScenarioItem>;
}

/** 预测结果中的活动信息 */
export interface ForecastEventInfo {
  event_id: string | null;
  event_name: string | null;
  event_type?: string | null;
  target_apps?: string[];
  uplift_estimate: ForecastUpliftEstimate;
  diff_analysis: ForecastDiffAnalysis;
  scenarios: ForecastScenarios;
}

/** 训练历史数据范围 */
export interface ForecastHistoryRange {
  start: string;
  end: string;
  buckets?: number;
}

/** 创建预测请求体（POST /predict） */
export interface ForecastPredictPayload {
  app_name: string;
  uri_template?: string;
  /** 预测时长：24h / 7d */
  horizon?: string;
  /** 场景：baseline / event_adjusted / scenario_compare */
  scenario?: string;
  include_interval?: boolean;
  /** 活动专项预测：指定活动 ID 后叠加活动影响 */
  event_id?: string;
  /** 强制预测（活动专项 / 人工强制纳入时使用，结果保留风险标识） */
  force?: boolean;
}

/** 创建预测响应（POST /predict） */
export interface ForecastPredictResult {
  forecast_id: string;
  app_name: string;
  uri_template?: string;
  model: string;
  scenario: string;
  points: ForecastPoint[];
  summary: ForecastSummary;
  quality?: Record<string, unknown>;
  /** 滚动回测指标（{策略名: 指标字典}） */
  backtest?: Record<string, Record<string, number | string | null>>;
  eligibility?: {
    status?: string;
    predictability?: string | null;
    score?: number | null;
  };
  risk_flags?: string[];
  /** 活动信息（仅活动调整场景返回） */
  event: ForecastEventInfo | null;
  data_source: string;
  generated_at?: string;
  history_range?: ForecastHistoryRange;
}

/** 历史实际值数据点（GET /history） */
export interface HistorySeriesPoint {
  timestamp: string;
  actual: number;
}

/** 历史实际值序列响应（GET /history） */
export interface HistorySeriesResult {
  app_name: string;
  uri_template: string;
  granularity: string;
  hours: number;
  count: number;
  data_source: string;
  points: HistorySeriesPoint[];
}

/** 回测指标查询参数（GET /evaluation） */
export interface ForecastEvaluationParams {
  app_name: string;
  uri_template?: string;
  granularity?: string;
  horizon?: string;
  folds?: number;
  models?: string;
}

/** 回测指标响应（GET /evaluation） */
export interface ForecastEvaluationResult {
  app_name: string;
  uri_template: string;
  granularity: string;
  horizon: string;
  folds: number;
  /** {策略名: {mae, wape, smape, coverage, improvement_vs_baseline...}} */
  backtest: Record<string, Record<string, number | string | null>>;
}

/**
 * 创建交易量预测（常规基线 / 活动调整）。
 * @param payload 预测参数（应用名必填，活动场景需携带 event_id）
 */
export const runForecast = async (
  payload: ForecastPredictPayload
): Promise<ForecastPredictResult> => {
  try {
    const response = await forecastClient.post<ForecastPredictResult>('predict', {
      app_name: payload.app_name,
      uri_template: payload.uri_template || '',
      horizon: payload.horizon || '24h',
      scenario: payload.scenario || 'baseline',
      include_interval: payload.include_interval !== false,
      event_id: payload.event_id || '',
      force: payload.force === true,
    }, { timeout: PREDICT_TIMEOUT });
    return response.data;
  } catch (error) {
    throw new Error(extractErrorMessage(error, '创建预测失败'));
  }
};

/**
 * 查询历史实际交易量序列（用于图表"实际值"曲线）。
 * @param params 应用名必填，hours 为最近 N 小时（1~720）
 */
export const fetchHistorySeries = async (params: {
  app_name: string;
  uri_template?: string;
  granularity?: string;
  hours?: number;
}): Promise<HistorySeriesResult> => {
  try {
    const response = await forecastClient.get<HistorySeriesResult>('history', {
      params: buildListParams({
        app_name: params.app_name,
        uri_template: params.uri_template,
        granularity: params.granularity,
        hours: params.hours,
      }),
    });
    const raw = (response.data || {}) as Partial<HistorySeriesResult>;
    return {
      app_name: raw.app_name || params.app_name,
      uri_template: raw.uri_template || '',
      granularity: raw.granularity || '5m',
      hours: Number(raw.hours ?? params.hours ?? 24),
      count: Number(raw.count ?? (Array.isArray(raw.points) ? raw.points.length : 0)),
      data_source: raw.data_source || 'mock',
      points: Array.isArray(raw.points) ? raw.points : [],
    };
  } catch (error) {
    throw new Error(extractErrorMessage(error, '获取历史实际值失败'));
  }
};

/**
 * 查询模型滚动回测指标（MAE / WAPE / sMAPE / 区间覆盖率 / 相对基线改善）。
 * 回测耗时较长，建议按需加载。
 * @param params 应用名必填
 */
export const fetchForecastEvaluation = async (
  params: ForecastEvaluationParams
): Promise<ForecastEvaluationResult> => {
  try {
    const response = await forecastClient.get<ForecastEvaluationResult>('evaluation', {
      params: buildListParams({
        app_name: params.app_name,
        uri_template: params.uri_template,
        granularity: params.granularity,
        horizon: params.horizon,
        folds: params.folds,
        models: params.models,
      }),
      timeout: EVALUATE_ALL_TIMEOUT,
    });
    const raw = (response.data || {}) as Partial<ForecastEvaluationResult>;
    return {
      app_name: raw.app_name || params.app_name,
      uri_template: raw.uri_template || '',
      granularity: raw.granularity || '5m',
      horizon: raw.horizon || params.horizon || '24h',
      folds: Number(raw.folds ?? 3),
      backtest: raw.backtest && typeof raw.backtest === 'object' ? raw.backtest : {},
    };
  } catch (error) {
    throw new Error(extractErrorMessage(error, '获取回测指标失败'));
  }
};
