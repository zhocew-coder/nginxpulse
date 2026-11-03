/**
 * 业务活动日历 API 封装（阶段四）。
 *
 * 活动接口已并入预测服务（8090），与预测资格服务同源。
 * 保留独立基础地址以便将来拆分部署，可通过 Vite 环境变量 VITE_EVENTS_API_BASE_URL 覆盖。
 * 后续若两服务合并，仅需调整该环境变量即可，无需改动业务代码。
 */
import axios from 'axios';

/** 活动服务默认基础地址（活动接口已并入预测服务，统一走宿主机 8090 端口） */
export const DEFAULT_EVENTS_BASE_URL = 'http://127.0.0.1:8090/api/forecast/v1';

/** 普通接口超时时间（毫秒） */
const REQUEST_TIMEOUT = 30000;

/** 活动类型 */
export type EventType = 'marketing' | 'batch' | 'promotion' | 'launch' | 'holiday';

/** 活动状态 */
export type EventStatus = 'draft' | 'confirmed' | 'completed' | 'cancelled';

/** 影响等级 */
export type ImpactLevel = 'low' | 'medium' | 'high';

/** 置信度 */
export type EventConfidence = 'high' | 'medium' | 'low';

/** 活动所处阶段 */
export type EventPhase = 'preheat' | 'active' | 'cooldown' | 'none';

/** 业务活动对象（列表与详情字段一致） */
export interface BusinessEvent {
  /** 内部代理主键：后端已从响应中剔除，保留为可选兼容字段 */
  id?: number;
  /** 业务活动 ID（唯一标识） */
  event_id: string;
  /** 活动名称 */
  event_name: string;
  /** 活动类型 */
  event_type: EventType | string;
  /** 活动开始时间（ISO8601，带时区） */
  start_time: string;
  /** 活动结束时间（ISO8601，带时区） */
  end_time: string;
  /** 预热开始时间，可为空 */
  preheat_start: string | null;
  /** 预热结束时间，可为空 */
  preheat_end: string | null;
  /** 回落结束时间，可为空 */
  cooldown_end: string | null;
  /** 受影响应用列表 */
  target_apps: string[];
  /** 受影响 URI 列表，为空数组表示该应用下全部 URL */
  target_uris: string[];
  /** 业务类型（如支付营销、清算批处理） */
  business_type: string;
  /** 影响等级 */
  impact_level: ImpactLevel | string;
  /** 预期增幅（百分比）；为 null 表示未标注，界面须按「数据不足」处理 */
  expected_uplift: number | null;
  /** 历史事件 ID，可为空 */
  historical_event_id: string | null;
  /** 活动负责人 */
  event_owner: string;
  /** 数据来源：mock / real */
  data_source: string;
  /** 置信度 */
  confidence: EventConfidence | string;
  /** 活动状态 */
  status: EventStatus | string;
  /** 创建时间（后端附加字段） */
  created_at?: string;
  /** 更新时间（后端附加字段） */
  updated_at?: string;
}

/** 活动列表查询参数 */
export interface EventListParams {
  status?: EventStatus | string;
  app_name?: string;
  start_from?: string;
  start_to?: string;
  event_type?: EventType | string;
  limit?: number;
  offset?: number;
}

/** 活动列表响应 */
export interface EventListResult {
  total: number;
  count: number;
  offset: number;
  events: BusinessEvent[];
}

/** 创建活动请求体 */
export interface CreateEventPayload {
  event_id?: string;
  event_name: string;
  event_type: EventType | string;
  start_time: string;
  end_time: string;
  preheat_start?: string | null;
  preheat_end?: string | null;
  cooldown_end?: string | null;
  target_apps: string[];
  target_uris?: string[];
  business_type?: string;
  impact_level?: ImpactLevel | string;
  expected_uplift?: number | null;
  historical_event_id?: string | null;
  event_owner?: string;
  data_source?: string;
  confidence?: EventConfidence | string;
  status?: EventStatus | string;
}

/** 创建活动响应 */
export interface CreateEventResult {
  ok: boolean;
  message: string;
  event: BusinessEvent;
}

/** 删除 / Mock 初始化等通用响应 */
export interface EventMutationResult {
  ok: boolean;
  message: string;
}

/** Mock 初始化响应 */
export interface InitMockEventsResult extends EventMutationResult {
  count: number;
  events: BusinessEvent[];
}

/** 阶段查询结果 */
export interface EventPhaseResult {
  event_id: string;
  ts: string;
  phase: EventPhase | string;
  /** 中文阶段名：预热期 / 正式期 / 回落期 / 不受影响 */
  phase_label: string;
  /** 该时点增幅，未标注时为 null */
  uplift: number | null;
  /** 后端说明文案（如「未标注预期增幅，按数据不足处理」） */
  note: string;
  confidence: EventConfidence | string;
}

/**
 * 活动接口异常：携带后端返回的中文校验错误数组。
 * 后端 400 返回 { detail: { message, errors: string[] } }，
 * 422 返回 Pydantic 的 { detail: [{ loc, msg }] }，二者在此统一。
 */
export class EventsApiError extends Error {
  /** 中文错误明细（可直接渲染展示） */
  errors: string[];

  constructor(message: string, errors: string[] = []) {
    super(message);
    this.name = 'EventsApiError';
    this.errors = errors;
  }
}

/**
 * 解析活动服务基础地址。
 * 优先使用构建期注入的 VITE_EVENTS_API_BASE_URL，否则回退到默认地址。
 */
function resolveBaseUrl(): string {
  const raw = String(import.meta.env?.VITE_EVENTS_API_BASE_URL || '').trim();
  return raw || DEFAULT_EVENTS_BASE_URL;
}

/** 当前生效的活动服务基础地址 */
export const EVENTS_API_BASE_URL = resolveBaseUrl();

/** 活动服务专用 axios 实例 */
const eventsClient = axios.create({
  baseURL: EVENTS_API_BASE_URL,
  timeout: REQUEST_TIMEOUT,
  headers: {
    'X-Requested-With': 'XMLHttpRequest',
    'Content-Type': 'application/json',
  },
});

/**
 * 把后端各类错误响应统一成 EventsApiError。
 * 覆盖三种形态：
 *   1) { detail: "文本" }
 *   2) { detail: { message, errors: string[] } }（业务校验 400）
 *   3) { detail: [{ loc, msg }] }（Pydantic 参数校验 422）
 * @param error 任意异常对象
 * @param fallback 兜底提示文案
 */
function extractError(error: unknown, fallback: string): EventsApiError {
  const responseData = (error as { response?: { data?: unknown } })?.response?.data;
  const data = (responseData || {}) as {
    detail?: unknown;
    error?: unknown;
    message?: unknown;
  };

  const detail = data.detail;
  if (typeof detail === 'string' && detail.trim()) {
    return new EventsApiError(detail);
  }
  if (detail && typeof detail === 'object') {
    if (Array.isArray(detail)) {
      const errors = detail
        .map((item: { msg?: unknown; loc?: unknown }) => {
          const msg = typeof item?.msg === 'string' ? item.msg : '';
          const loc = Array.isArray(item?.loc) ? item.loc.slice(1).join('.') : '';
          return loc ? `${loc}：${msg}` : msg;
        })
        .filter((text: string) => Boolean(text));
      if (errors.length > 0) {
        return new EventsApiError('活动参数校验失败', errors);
      }
    } else {
      const wrapper = detail as { message?: unknown; errors?: unknown };
      const errors = Array.isArray(wrapper.errors) ? wrapper.errors.map((item) => String(item)) : [];
      const message = typeof wrapper.message === 'string' && wrapper.message.trim() ? wrapper.message : '';
      if (message || errors.length > 0) {
        return new EventsApiError(message || fallback, errors);
      }
    }
  }

  const topMessage = data.error ?? data.message;
  if (typeof topMessage === 'string' && topMessage.trim()) {
    return new EventsApiError(topMessage);
  }

  return new EventsApiError(fallback);
}

/**
 * 构造查询串，跳过空值参数。
 * @param params 查询参数
 */
function buildQuery(params: Record<string, unknown> = {}): Record<string, string> {
  const query: Record<string, string> = {};
  Object.keys(params).forEach((key) => {
    const value = params[key];
    if (value !== undefined && value !== null && value !== '') {
      query[key] = String(value);
    }
  });
  return query;
}

/**
 * 查询活动列表（按 start_time 倒序）。
 * @param params 状态 / 应用名 / 时间区间 / 类型 / 分页参数
 */
export const fetchEvents = async (params: EventListParams = {}): Promise<EventListResult> => {
  try {
    const response = await eventsClient.get<unknown>('events', {
      params: buildQuery(params),
    });
    const raw = (response.data || {}) as Partial<EventListResult>;
    const list = Array.isArray(raw.events) ? raw.events : [];
    return {
      total: Number(raw.total ?? list.length),
      count: Number(raw.count ?? list.length),
      offset: Number(raw.offset ?? params.offset ?? 0),
      events: list,
    };
  } catch (error) {
    throw extractError(error, '获取活动列表失败');
  }
};

/**
 * 查询单个活动详情。
 * @param eventId 业务活动 ID
 */
export const fetchEvent = async (eventId: string): Promise<BusinessEvent> => {
  try {
    const response = await eventsClient.get<BusinessEvent>(`events/${encodeURIComponent(eventId)}`);
    return response.data;
  } catch (error) {
    throw extractError(error, '获取活动详情失败');
  }
};

/**
 * 创建活动。
 * @param payload 活动参数（校验失败会抛出携带中文 errors 的 EventsApiError）
 */
export const createEvent = async (payload: CreateEventPayload): Promise<CreateEventResult> => {
  try {
    const response = await eventsClient.post<CreateEventResult>('events', payload);
    const raw = (response.data || {}) as Partial<CreateEventResult>;
    return {
      ok: raw.ok !== false,
      message: raw.message || '活动已创建',
      event: raw.event as BusinessEvent,
    };
  } catch (error) {
    throw extractError(error, '创建活动失败');
  }
};

/**
 * 删除活动。
 * @param eventId 业务活动 ID
 */
export const deleteEvent = async (eventId: string): Promise<EventMutationResult> => {
  try {
    const response = await eventsClient.delete<EventMutationResult>(
      `events/${encodeURIComponent(eventId)}`
    );
    const raw = (response.data || {}) as Partial<EventMutationResult>;
    return {
      ok: raw.ok !== false,
      message: raw.message || '活动已删除',
    };
  } catch (error) {
    throw extractError(error, '删除活动失败');
  }
};

/**
 * 灌入内置 Mock 活动（演示用）。
 */
export const initMockEvents = async (): Promise<InitMockEventsResult> => {
  try {
    const response = await eventsClient.post<InitMockEventsResult>('events/init-mock');
    const raw = (response.data || {}) as Partial<InitMockEventsResult>;
    return {
      ok: raw.ok !== false,
      message: raw.message || 'Mock 活动已初始化',
      count: Number(raw.count ?? (Array.isArray(raw.events) ? raw.events.length : 0)),
      events: Array.isArray(raw.events) ? raw.events : [],
    };
  } catch (error) {
    throw extractError(error, '初始化 Mock 活动失败');
  }
};

/**
 * 查询活动在指定时刻所处阶段（日历染色 / 时点解读）。
 * 注意：ts 需为带时区的 ISO8601，且必须做 URL 编码（+ 号会被解码为空格）。
 * @param eventId 业务活动 ID
 * @param ts ISO8601 时间字符串（带时区）
 */
export const fetchEventPhase = async (eventId: string, ts: string): Promise<EventPhaseResult> => {
  try {
    const response = await eventsClient.get<EventPhaseResult>(
      `events/${encodeURIComponent(eventId)}/phase`,
      { params: { ts } }
    );
    return response.data;
  } catch (error) {
    throw extractError(error, '查询活动阶段失败');
  }
};
