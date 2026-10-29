import client from './client';
import type { ApiResponse } from './types';

export interface AIQueryRequest {
  question: string;
}

export interface AIQueryResponse {
  question?: string;
  sql: string;
  answer: string;
  /** 查询返回的原始行数据（后端字段为 results，此处已规范化为 data） */
  data: any[];
  count?: number;
  /** LLM 从业务视角的解读 */
  business_insight?: string;
  /** LLM 给出的运维建议 */
  ops_advice?: string[];
  /** 数据中的关键发现 */
  highlights?: string[];
  /** 风险提示 */
  risk_alerts?: string[];
  llm_generated?: boolean;
  success: boolean;
}

export interface AnomalyDetectRequest {
  hours?: number;
  threshold?: number;
}

export interface AnomalyReport {
  id: number;
  type: string;
  severity: string;
  source_ips: string[];
  request_count: number;
  share_pct?: number;
  top_urls?: { url: string; count: number }[];
  time_range: string;
  evidence: string[];
  created_at: string;
  /** LLM 生成的异常标题 */
  title?: string;
  /** LLM 风险研判 */
  risk_analysis?: string;
  /** LLM 影响面分析 */
  impact?: string;
  /** LLM 处置建议（按紧急程度排序） */
  actions?: string[];
  /** LLM 研判置信度 0-1 */
  confidence?: number;
  llm_generated?: boolean;
}

/** 汇总式 heavy_hitter 研判 */
export interface HeavyHitterSummary {
  risk_analysis?: string;
  impact?: string;
  actions?: string[];
  confidence?: number;
  llm_generated?: boolean;
}

/** 单个异常 IP 的汇总数据（用于图表渲染） */
export interface HeavyHitterEntry {
  ip: string;
  share_pct: number;
  request_count: number;
  top_urls?: { url: string; count: number }[];
}

export interface AnomalyDetectResponse {
  anomalies: AnomalyReport[];
  total: number;
  /** 实际检测的时长窗口 */
  hours?: number;
  /** 其中由 LLM 完成研判的数量 */
  llmAnalyzed?: number;
  message?: string;
  /** heavy_hitter 汇总数据（图表渲染用） */
  heavyHitters?: HeavyHitterEntry[];
  /** heavy_hitter 合计占比 */
  hitterTotalShare?: number;
  /** heavy_hitter 汇总式 LLM 研判 */
  hitterSummary?: HeavyHitterSummary;
}

export interface ReportGenerateRequest {
  type: 'daily' | 'weekly' | 'monthly';
  date?: string;
}

export interface ReportData {
  id?: number;
  type: string;
  title?: string;
  period?: string;
  generated_at?: string;
  summary: string;
  content?: string;
  insights?: string[];
  recommendations?: string[];
  predictions?: Array<{ metric: string; value: number; confidence: number; trend: string }>;
  metrics: Record<string, any>;
  created_at?: string;
}

export interface ReportGenerateResponse {
  report?: ReportData;
  success?: boolean;
}

/**
 * 后端 /api/ai/query 返回扁平结构：
 * { question, sql, results, count, answer, business_insight, ops_advice, ... }
 * 这里统一规范化成前端使用的形状（results -> data），避免每个调用方各自适配。
 */
export const aiQuery = async (question: string): Promise<AIQueryResponse> => {
  const response = await client.post<ApiResponse<any>>(
    'api/ai/query',
    { question },
    { timeout: 90000 }
  );
  const raw: any = response.data || {};
  return {
    question: raw.question ?? question,
    sql: raw.sql ?? '',
    answer: raw.answer ?? '',
    data: Array.isArray(raw.results) ? raw.results : [],
    count: raw.count ?? (Array.isArray(raw.results) ? raw.results.length : 0),
    business_insight: raw.business_insight ?? '',
    ops_advice: Array.isArray(raw.ops_advice) ? raw.ops_advice : [],
    highlights: Array.isArray(raw.highlights) ? raw.highlights : [],
    risk_alerts: Array.isArray(raw.risk_alerts) ? raw.risk_alerts : [],
    llm_generated: Boolean(raw.llm_generated),
    success: true,
  };
};

/**
 * 后端 /api/ai/anomalies/detect 返回 { reports, count, hours, llm_analyzed }
 * 这里规范化为 { anomalies, total }。LLM 研判耗时较长，超时放宽到 120s。
 */
export const detectAnomalies = async (
  hours = 24,
  threshold = 3
): Promise<AnomalyDetectResponse> => {
  const response = await client.post<ApiResponse<any>>(
    'api/ai/anomalies/detect',
    { hours, threshold },
    { timeout: 180000 }
  );
  const raw: any = response.data || {};
  const reports = Array.isArray(raw.reports) ? raw.reports : [];
  return {
    anomalies: reports,
    total: raw.count ?? reports.length,
    hours: raw.hours ?? hours,
    llmAnalyzed: raw.llm_analyzed ?? 0,
    message: raw.message,
    heavyHitters: Array.isArray(raw.heavy_hitters) ? raw.heavy_hitters : [],
    hitterTotalShare: raw.hitter_total_share ?? 0,
    hitterSummary: raw.hitter_summary,
  };
};

export const fetchAnomalies = async (
  hours = 24
): Promise<AnomalyDetectResponse> => {
  const response = await client.get<ApiResponse<any>>('api/ai/anomalies', {
    params: { hours },
  });
  const raw: any = response.data || {};
  const reports = Array.isArray(raw.reports) ? raw.reports : [];
  return {
    anomalies: reports,
    total: raw.count ?? reports.length,
    hours,
  };
};

export const generateReport = async (
  type: 'daily' | 'weekly' | 'monthly',
  date?: string,
  refresh = false
): Promise<ReportData> => {
  const response = await client.post<ApiResponse<ReportData>>(
    'api/ai/reports/generate',
    { type, date, refresh },
    { timeout: 120000 }
  );
  // 后端直接返回 report 对象，而非 { report: ... } 包裹
  const data = response.data as unknown as ReportData;
  return data;
};

export const fetchDailyReport = async (date: string): Promise<ReportData> => {
  const response = await client.get<ApiResponse<ReportData>>('api/ai/reports/daily', {
    params: { date },
  });
  return response.data;
};
