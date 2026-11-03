/** 东八区（北京时间）相对 UTC 的偏移量，单位毫秒 */
export const BEIJING_OFFSET_MS = 8 * 60 * 60 * 1000;

/** 一天的毫秒数 */
export const DAY_MS = 24 * 60 * 60 * 1000;

/** 北京时间日历/时钟分量 */
export interface BeijingParts {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
  second: number;
}

/**
 * 把绝对时间戳换算成东八区（北京时间）的日历与时钟分量。
 * 预测相关页面统一按业务时区（UTC+8）展示与分日，
 * 避免浏览器 / 容器时区差异导致时间偏移 8 小时或跨天。
 * @param ms 绝对时间戳（毫秒）
 */
export const toBeijingParts = (ms: number): BeijingParts => {
  const shifted = new Date(ms + BEIJING_OFFSET_MS);
  return {
    year: shifted.getUTCFullYear(),
    month: shifted.getUTCMonth() + 1,
    day: shifted.getUTCDate(),
    hour: shifted.getUTCHours(),
    minute: shifted.getUTCMinutes(),
    second: shifted.getUTCSeconds(),
  };
};

const pad2 = (value: number): string => String(value).padStart(2, '0');

/**
 * 按东八区格式化时间：「yyyy-MM-dd HH:mm」。
 * @param value ISO 时间字符串或时间戳，解析失败返回 '—'
 */
export const formatBeijingDateTime = (value?: string | number | null): string => {
  const ms = typeof value === 'number' ? value : parseTimestamp(value);
  if (ms === null) {
    return '—';
  }
  const parts = toBeijingParts(ms);
  return `${parts.year}-${pad2(parts.month)}-${pad2(parts.day)} ${pad2(parts.hour)}:${pad2(parts.minute)}`;
};

/**
 * 按东八区格式化时间（含秒）：「yyyy-MM-dd HH:mm:ss」。
 * @param value ISO 时间字符串或时间戳，解析失败返回 '—'
 */
export const formatBeijingDateTimeWithSeconds = (value?: string | number | null): string => {
  const ms = typeof value === 'number' ? value : parseTimestamp(value);
  if (ms === null) {
    return '—';
  }
  const parts = toBeijingParts(ms);
  return `${parts.year}-${pad2(parts.month)}-${pad2(parts.day)} ${pad2(parts.hour)}:${pad2(parts.minute)}:${pad2(parts.second)}`;
};

/**
 * 解析时间字符串为时间戳，失败返回 null。
 * @param value ISO 时间字符串
 */
export const parseTimestamp = (value?: string | number | null): number | null => {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  const ms = typeof value === 'number' ? value : new Date(value).getTime();
  return Number.isNaN(ms) ? null : ms;
};

/**
 * 生成东八区日期 key：「yyyy-mm-dd」。
 * @param ms 绝对时间戳（毫秒）
 */
export const beijingDayKey = (ms: number): string => {
  const parts = toBeijingParts(ms);
  return `${parts.year}-${pad2(parts.month)}-${pad2(parts.day)}`;
};

/**
 * 计算某个「东八区自然日」对应的绝对时间区间 [起, 止]（止为 23:59:59.999）。
 * 日历染色与按日分组均以此为边界，避免跨时区造成的跨天误差。
 * @param year 年
 * @param month 月（1-12）
 * @param day 日
 */
export const beijingDayRange = (
  year: number,
  month: number,
  day: number
): { start: number; end: number } => {
  const start = Date.UTC(year, month - 1, day) - BEIJING_OFFSET_MS;
  return { start, end: start + DAY_MS - 1 };
};

export const formatDate = (date: Date): string => {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
};

export const formatTraffic = (traffic: number): string => {
  if (traffic < 1024) {
    return `${traffic.toFixed(2)} B`;
  }
  if (traffic < 1024 * 1024) {
    return `${(traffic / 1024).toFixed(2)} KB`;
  }
  if (traffic < 1024 * 1024 * 1024) {
    return `${(traffic / (1024 * 1024)).toFixed(2)} MB`;
  }
  if (traffic < 1024 * 1024 * 1024 * 1024) {
    return `${(traffic / (1024 * 1024 * 1024)).toFixed(2)} GB`;
  }
  return `${(traffic / (1024 * 1024 * 1024 * 1024)).toFixed(2)} TB`;
};

export const saveUserPreference = (key: string, value: string): void => {
  localStorage.setItem(key, value);
};

export const getUserPreference = <T extends string>(key: string, defaultValue: T): T => {
  const saved = localStorage.getItem(key);
  return (saved || defaultValue) as T;
};

export {
  getInitialServerStatusEnabled,
  getMobileBasePathWithSlash,
  getWebBasePath,
  getWebBasePathWithSlash,
} from './base-path';
