<template>
  <div class="event-impact-page">
    <header class="page-header">
      <div class="page-title">
        <span class="title-chip">活动影响分析</span>
        <p class="title-sub">
          对业务活动执行活动专项预测，从「vs 基线 / 历史同期 / 活动前后 / DID 双差分」四个视角量化活动影响，
          并给出保守 / 基准 / 乐观三情景对比。时间统一按北京时间（UTC+8）展示。
        </p>
      </div>
      <div class="header-actions">
        <Button
          label="重新分析"
          icon="pi pi-refresh"
          outlined
          :loading="analyzing"
          :disabled="!canAnalyze"
          @click="loadAnalysis"
        />
      </div>
    </header>

    <Message v-if="isMockData" severity="warn" :closable="false" class="mock-banner">
      <div class="mock-banner-content">
        <Tag value="Mock" severity="warn" class="mock-banner-tag" />
        <span>当前为 Mock 演示数据，不可用于生产报告。</span>
      </div>
    </Message>

    <Message v-if="loadError" severity="error" :closable="false" class="mock-banner">
      <div class="mock-banner-content">
        <span>{{ loadError }}</span>
        <Button label="重试" icon="pi pi-refresh" text size="small" :disabled="!canAnalyze" @click="loadAnalysis" />
      </div>
    </Message>

    <Message v-if="optionsError" severity="warn" :closable="false" class="mock-banner">
      <div class="mock-banner-content">
        <span>{{ optionsError }}</span>
        <Button label="重试" icon="pi pi-refresh" text size="small" @click="loadOptions" />
      </div>
    </Message>

    <!-- 筛选栏 -->
    <section class="card filter-card" data-anim>
      <div class="filter-toolbar">
        <div class="filter-field">
          <label class="filter-label" for="impact-event-filter">业务活动</label>
          <Dropdown
            v-model="selectedEventId"
            inputId="impact-event-filter"
            class="filter-dropdown"
            :options="eventOptions"
            optionLabel="label"
            optionValue="value"
            placeholder="请选择活动"
            :loading="optionsLoading"
            showClear
            @change="handleEventChange"
          />
        </div>
        <div class="filter-field">
          <label class="filter-label" for="impact-app-filter">应用名称</label>
          <Dropdown
            v-model="selectedApp"
            inputId="impact-app-filter"
            class="filter-dropdown"
            :options="appOptions"
            optionLabel="label"
            optionValue="value"
            placeholder="请选择应用"
            :disabled="!selectedEventId"
            showClear
          />
        </div>
        <div class="filter-spacer"></div>
        <div class="filter-actions">
          <Button
            label="执行分析"
            icon="pi pi-search"
            :loading="analyzing"
            :disabled="!canAnalyze"
            @click="loadAnalysis"
          />
        </div>
      </div>
      <div class="filter-summary">
        分析口径：对所选应用执行活动专项预测（未来 24 小时），活动增幅仅来自历史实测或活动计划参数，数据不足时增量为 0 并明确标注，不编造数值。
      </div>
    </section>

    <!-- 活动信息卡片 -->
    <section v-if="selectedEvent" class="card event-info-card" data-anim>
      <div class="card-header">
        <div class="card-title">
          <span class="card-icon orange"><i class="ri-calendar-event-line"></i></span>
          活动信息
        </div>
        <div class="event-info-tags">
          <Tag :value="typeLabel(selectedEvent.event_type)" severity="info" />
          <Tag :value="statusLabel(selectedEvent.status)" :severity="statusSeverity(selectedEvent.status)" />
          <Tag :value="`影响等级：${impactLabel(selectedEvent.impact_level)}`" :severity="impactSeverity(selectedEvent.impact_level)" />
        </div>
      </div>
      <div class="event-info-grid">
        <div class="event-info-item">
          <span class="event-info-label">活动名称</span>
          <span class="event-info-value">{{ selectedEvent.event_name }}</span>
        </div>
        <div class="event-info-item">
          <span class="event-info-label">活动 ID</span>
          <span class="event-info-value">{{ selectedEvent.event_id }}</span>
        </div>
        <div class="event-info-item">
          <span class="event-info-label">正式期</span>
          <span class="event-info-value">
            {{ formatBeijingDateTime(selectedEvent.start_time) }} ~ {{ formatBeijingDateTime(selectedEvent.end_time) }}
          </span>
        </div>
        <div class="event-info-item">
          <span class="event-info-label">预热期</span>
          <span class="event-info-value">{{ preheatRangeText }}</span>
        </div>
        <div class="event-info-item">
          <span class="event-info-label">回落期</span>
          <span class="event-info-value">{{ cooldownRangeText }}</span>
        </div>
        <div class="event-info-item">
          <span class="event-info-label">影响应用</span>
          <span class="event-info-value">{{ targetAppsText }}</span>
        </div>
        <div class="event-info-item">
          <span class="event-info-label">计划增幅（expected_uplift）</span>
          <span class="event-info-value">{{ expectedUpliftText }}</span>
        </div>
        <div class="event-info-item">
          <span class="event-info-label">增幅估计（uplift_estimate）</span>
          <span class="event-info-value">{{ upliftEstimateText }}</span>
        </div>
      </div>
    </section>

    <!-- 差分分析四象限 -->
    <section class="diff-section" data-anim>
      <div class="section-title">
        <span class="section-title-chip">差分分析四象限</span>
        <span class="section-title-hint">四种口径互相印证；无对照组时 DID 明确标注为「同期差异估算」，不作因果结论。</span>
      </div>
      <div class="diff-grid">
        <!-- ① vs 基线 -->
        <div class="card diff-card">
          <div class="diff-card-head">
            <span class="diff-index">①</span>
            <span class="diff-name">vs 基线对比</span>
          </div>
          <div ref="diffChart1Ref" class="diff-chart"></div>
          <div v-if="method1" class="diff-metrics">
            <div class="diff-metric-row">
              <span>总增量</span>
              <span>{{ formatAmount(method1.total_increment) }}</span>
            </div>
            <div class="diff-metric-row">
              <span>增幅比例</span>
              <span>{{ formatPercent(method1.uplift_ratio) }}</span>
            </div>
            <div class="diff-metric-row">
              <span>峰值增量</span>
              <span>{{ formatAmount(method1.peak_increment) }}</span>
            </div>
            <div class="diff-metric-row">
              <span>影响时长</span>
              <span>{{ method1.impact_duration_points ?? '—' }} 个时间桶</span>
            </div>
          </div>
          <div v-else class="diff-empty">执行分析后展示</div>
        </div>

        <!-- ② 历史同期 -->
        <div class="card diff-card">
          <div class="diff-card-head">
            <span class="diff-index">②</span>
            <span class="diff-name">历史同期对比</span>
          </div>
          <div v-if="method2 && method2.available" class="diff-metrics diff-metrics-full">
            <div class="diff-metric-row">
              <span>本期活动总量</span>
              <span>{{ formatAmount(method2.current_event_total) }}</span>
            </div>
            <div class="diff-metric-row">
              <span>基线总量</span>
              <span>{{ formatAmount(method2.baseline_total) }}</span>
            </div>
            <div class="diff-metric-row">
              <span>同比增幅</span>
              <span>{{ method2.yoy_growth === null || method2.yoy_growth === undefined ? '数据不足' : formatPercent(method2.yoy_growth) }}</span>
            </div>
            <div v-if="method2.note" class="diff-note">{{ method2.note }}</div>
            <div v-if="method2.reason" class="diff-note">{{ method2.reason }}</div>
          </div>
          <div v-else-if="method2" class="diff-unavailable">
            <Tag value="数据不足" severity="warn" />
            <span>{{ method2.reason || '无历史同期数据，无法进行同期差分' }}</span>
          </div>
          <div v-else class="diff-empty">执行分析后展示</div>
        </div>

        <!-- ③ 活动前后 -->
        <div class="card diff-card">
          <div class="diff-card-head">
            <span class="diff-index">③</span>
            <span class="diff-name">活动前后对比</span>
          </div>
          <div ref="diffChart3Ref" class="diff-chart"></div>
          <div v-if="method3" class="diff-metrics">
            <div class="diff-metric-row">
              <span>预热增长</span>
              <span>{{ formatPercent(method3.preheat_growth_vs_baseline) }}</span>
            </div>
            <div class="diff-metric-row">
              <span>期间增长</span>
              <span>{{ formatPercent(method3.active_growth_vs_baseline) }}</span>
            </div>
            <div class="diff-metric-row">
              <span>回落速度</span>
              <span>{{ formatPercent(method3.cooldown_decay_rate) }}</span>
            </div>
            <div v-if="method3.note" class="diff-note">{{ method3.note }}</div>
          </div>
          <div v-else class="diff-empty">执行分析后展示</div>
        </div>

        <!-- ④ DID -->
        <div class="card diff-card">
          <div class="diff-card-head">
            <span class="diff-index">④</span>
            <span class="diff-name">DID 双差分</span>
            <Tag v-if="method4 && !method4.available" value="同期差异估算" severity="warn" class="diff-badge" />
          </div>
          <div v-if="method4 && method4.available" class="diff-metrics diff-metrics-full">
            <div class="diff-metric-row">
              <span>处理组增量</span>
              <span>{{ formatAmount(method4.treated_increment) }}</span>
            </div>
            <div class="diff-metric-row">
              <span>对照组增量</span>
              <span>{{ formatAmount(method4.control_increment) }}</span>
            </div>
            <div class="diff-metric-row">
              <span>DID 净影响</span>
              <span>{{ formatAmount(method4.did_net_effect) }}</span>
            </div>
            <div v-if="method4.note" class="diff-note">{{ method4.note }}</div>
          </div>
          <div v-else-if="method4" class="diff-unavailable">
            <span>{{ method4.reason || '未找到合理对照组，当前结果仅为「同期差异估算」' }}</span>
          </div>
          <div v-else class="diff-empty">执行分析后展示</div>
        </div>
      </div>
    </section>

    <!-- 三情景对比 -->
    <section class="card scenario-card" data-anim>
      <div class="card-header">
        <div class="card-title">
          <span class="card-icon green"><i class="ri-line-chart-line"></i></span>
          三情景对比（保守 0.6x / 基准 1.0x / 乐观 1.4x）
        </div>
      </div>
      <div v-if="scenarios && scenarios.available" class="scenario-body">
        <div ref="scenarioChartRef" class="scenario-chart"></div>
        <div class="scenario-table-wrap">
          <table class="scenario-table">
            <thead>
              <tr>
                <th>情景</th>
                <th>情景系数</th>
                <th>预测总量</th>
                <th>活动增量</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in scenarioRows" :key="`scenario-${row.key}`">
                <td>{{ row.label }}</td>
                <td>{{ row.factor }}x</td>
                <td>{{ formatAmount(row.total) }}</td>
                <td>{{ formatAmount(row.increment) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      <div v-else-if="scenarios" class="scenario-unavailable">
        <Tag value="数据不足" severity="warn" />
        <span>{{ scenarios.reason || '缺少活动增幅依据，仅展示常规基线，不编造情景数值' }}</span>
      </div>
      <div v-else class="summary-empty">执行分析后展示三情景对比</div>
    </section>

    <!-- 活动阶段时间线 -->
    <section v-if="selectedEvent" class="card timeline-card" data-anim>
      <div class="card-header">
        <div class="card-title">
          <span class="card-icon blue"><i class="ri-time-line"></i></span>
          活动阶段时间线
        </div>
        <div class="timeline-legend">
          <span class="legend-item"><i class="legend-dot preheat"></i>预热期</span>
          <span class="legend-item"><i class="legend-dot active"></i>正式期</span>
          <span class="legend-item"><i class="legend-dot cooldown"></i>回落期</span>
        </div>
      </div>
      <div class="timeline-track">
        <div
          v-for="segment in timelineSegments"
          :key="`tl-${segment.key}`"
          class="timeline-segment"
          :class="segment.key"
          :style="{ width: `${segment.percent}%` }"
        >
          <span class="timeline-segment-label">{{ segment.label }}</span>
        </div>
      </div>
      <div class="timeline-axis">
        <span>{{ timelineStartText }}</span>
        <span>{{ timelineEndText }}</span>
      </div>
      <div class="timeline-details">
        <div v-for="segment in timelineSegments" :key="`tld-${segment.key}`" class="timeline-detail">
          <span class="timeline-detail-dot" :class="segment.key"></span>
          <span class="timeline-detail-label">{{ segment.label }}</span>
          <span class="timeline-detail-range">{{ segment.rangeText }}</span>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
/**
 * 活动影响分析页（阶段六交付物）。
 * 展示活动信息、差分分析四象限、三情景对比与活动阶段时间线。
 * 页面文案全部为中文硬编码，时间统一按北京时间（UTC+8）展示。
 */
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue';
import * as echarts from 'echarts';
import type { EChartsType } from 'echarts/core';
import Button from 'primevue/button';
import Dropdown from 'primevue/dropdown';
import Message from 'primevue/message';
import Tag from 'primevue/tag';
import { fetchEvents } from '@/api/events';
import type { BusinessEvent } from '@/api/events';
import { fetchEligibilityList, runForecast } from '@/api/forecast';
import type {
  ForecastDiffAnalysis,
  ForecastDiffMethod1,
  ForecastDiffMethod2,
  ForecastDiffMethod3,
  ForecastDiffMethod4,
  ForecastPredictResult,
  ForecastScenarios,
} from '@/api/forecast';
import { formatBeijingDateTime, parseTimestamp } from '@/utils';

/** 活动类型中文标签 */
const TYPE_LABELS: Record<string, string> = {
  marketing: '营销活动',
  batch: '批处理',
  promotion: '促销活动',
  launch: '上线发布',
  holiday: '节假日',
};

/** 活动状态中文标签 */
const STATUS_LABELS: Record<string, string> = {
  draft: '草稿',
  confirmed: '已确认',
  completed: '已完成',
  cancelled: '已取消',
};

/** 活动状态语义色 */
const STATUS_SEVERITIES: Record<string, string> = {
  draft: 'secondary',
  confirmed: 'success',
  completed: 'info',
  cancelled: 'danger',
};

/** 影响等级中文标签 */
const IMPACT_LABELS: Record<string, string> = {
  low: '低',
  medium: '中',
  high: '高',
};

/** 影响等级语义色 */
const IMPACT_SEVERITIES: Record<string, string> = {
  low: 'secondary',
  medium: 'warn',
  high: 'danger',
};

/** 置信度中文标签 */
const CONFIDENCE_LABELS: Record<string, string> = {
  high: '高',
  medium: '中',
  low: '低',
};

/** 增幅来源中文标签 */
const UPLIFT_SOURCE_LABELS: Record<string, string> = {
  history: '历史实测',
  plan: '活动计划参数',
  manual: '人工标注',
};

/** 三情景中文标签与顺序 */
const SCENARIO_ROWS = [
  { key: 'conservative', label: '保守情景' },
  { key: 'baseline', label: '基准情景' },
  { key: 'optimistic', label: '乐观情景' },
];

/** 图表配色 */
const COLOR_BASELINE = '#1d6bff';
const COLOR_ADJUSTED = '#f97316';
const COLOR_PREHEAT = '#3b82f6';
const COLOR_ACTIVE = '#f59e0b';
const COLOR_COOLDOWN = '#10b981';

const eventOptions = ref<Array<{ label: string; value: string }>>([]);
const appOptions = ref<Array<{ label: string; value: string }>>([]);
const eventList = ref<BusinessEvent[]>([]);
/** 活动未标注影响应用时的备选应用列表（来自预测对象） */
const fallbackAppNames = ref<string[]>([]);

const selectedEventId = ref<string>('');
const selectedApp = ref<string>('');

const optionsLoading = ref(false);
const optionsError = ref('');
const analyzing = ref(false);
const loadError = ref('');
const result = ref<ForecastPredictResult | null>(null);

const diffChart1Ref = ref<HTMLElement | null>(null);
const diffChart3Ref = ref<HTMLElement | null>(null);
const scenarioChartRef = ref<HTMLElement | null>(null);
let diffChart1: EChartsType | null = null;
let diffChart3: EChartsType | null = null;
let scenarioChart: EChartsType | null = null;

/** 当前选中活动 */
const selectedEvent = computed<BusinessEvent | null>(() => {
  if (!selectedEventId.value) {
    return null;
  }
  return eventList.value.find((event) => event.event_id === selectedEventId.value) || null;
});

/** 是否可执行分析 */
const canAnalyze = computed(
  () => Boolean(selectedEventId.value) && Boolean(selectedApp.value) && !analyzing.value
);

/** 是否 Mock 数据 */
const isMockData = computed(() => {
  if (result.value) {
    return String(result.value.data_source || '').toLowerCase() === 'mock';
  }
  return String(selectedEvent.value?.data_source || '').toLowerCase() === 'mock';
});

/** 差分分析汇总 */
const diffAnalysis = computed<ForecastDiffAnalysis | null>(() => {
  return result.value?.event?.diff_analysis || null;
});

const method1 = computed<ForecastDiffMethod1 | null>(() => diffAnalysis.value?.method1_vs_baseline || null);
const method2 = computed<ForecastDiffMethod2 | null>(
  () => diffAnalysis.value?.method2_historical_same_period || null
);
const method3 = computed<ForecastDiffMethod3 | null>(() => diffAnalysis.value?.method3_before_after || null);
const method4 = computed<ForecastDiffMethod4 | null>(() => diffAnalysis.value?.method4_did || null);

/** 三情景对比 */
const scenarios = computed<ForecastScenarios | null>(() => result.value?.event?.scenarios || null);

/** 三情景表格行 */
const scenarioRows = computed(() => {
  const data = scenarios.value?.scenarios || {};
  return SCENARIO_ROWS.map((row) => {
    const item = data[row.key];
    return {
      key: row.key,
      label: row.label,
      factor: item ? item.factor : '—',
      total: item ? item.total : null,
      increment: item ? item.increment : null,
    };
  });
});

/** 预热期时间范围文案 */
const preheatRangeText = computed(() => {
  const event = selectedEvent.value;
  if (!event) {
    return '—';
  }
  if (!event.preheat_start) {
    return '未设置';
  }
  const end = event.preheat_end || event.start_time;
  return `${formatBeijingDateTime(event.preheat_start)} ~ ${formatBeijingDateTime(end)}`;
});

/** 回落期时间范围文案 */
const cooldownRangeText = computed(() => {
  const event = selectedEvent.value;
  if (!event) {
    return '—';
  }
  if (!event.cooldown_end) {
    return '未设置';
  }
  return `${formatBeijingDateTime(event.end_time)} ~ ${formatBeijingDateTime(event.cooldown_end)}`;
});

/** 影响应用文案 */
const targetAppsText = computed(() => {
  const apps = selectedEvent.value?.target_apps || [];
  return apps.length > 0 ? apps.join('、') : '全部应用';
});

/** 计划增幅文案（null 按「数据不足」处理，不显示 0） */
const expectedUpliftText = computed(() => {
  const value = selectedEvent.value?.expected_uplift;
  if (value === null || value === undefined) {
    return '数据不足 / 未标注';
  }
  return formatSignedPercent(value);
});

/** 增幅估计文案 */
const upliftEstimateText = computed(() => {
  const estimate = result.value?.event?.uplift_estimate;
  if (!estimate) {
    return '执行分析后展示';
  }
  if (estimate.uplift === null || estimate.uplift === undefined) {
    return `数据不足（来源：${upliftSourceLabel(estimate.source)}，置信度：${confidenceLabel(estimate.confidence)}）`;
  }
  return `${formatSignedPercent(estimate.uplift)}（来源：${upliftSourceLabel(estimate.source)}，置信度：${confidenceLabel(estimate.confidence)}）`;
});

/** 时间线片段 */
const timelineSegments = computed(() => {
  const event = selectedEvent.value;
  if (!event) {
    return [];
  }
  const start = parseTimestamp(event.start_time);
  const end = parseTimestamp(event.end_time);
  const preheatStart = parseTimestamp(event.preheat_start);
  const preheatEnd = parseTimestamp(event.preheat_end) ?? start;
  const cooldownEnd = parseTimestamp(event.cooldown_end);
  const allTs = [start, end, preheatStart, preheatEnd, cooldownEnd].filter(
    (ts): ts is number => ts !== null
  );
  if (allTs.length === 0) {
    return [];
  }
  const rangeStart = Math.min(...allTs);
  const rangeEnd = Math.max(...allTs);
  const span = Math.max(rangeEnd - rangeStart, 1);

  const raw: Array<{ key: string; label: string; start: number | null; end: number | null }> = [
    {
      key: 'preheat',
      label: '预热期',
      start: preheatStart,
      end: preheatEnd,
    },
    {
      key: 'active',
      label: '正式期',
      start,
      end,
    },
    {
      key: 'cooldown',
      label: '回落期',
      start: end,
      end: cooldownEnd,
    },
  ];

  return raw
    .filter((item) => item.start !== null && item.end !== null && item.end > item.start)
    .map((item) => {
      const segStart = item.start as number;
      const segEnd = item.end as number;
      return {
        key: item.key,
        label: item.label,
        percent: Math.max(((segEnd - segStart) / span) * 100, 2),
        rangeText: `${formatBeijingDateTime(segStart)} ~ ${formatBeijingDateTime(segEnd)}`,
      };
    });
});

/** 时间线起点文案 */
const timelineStartText = computed(() => {
  const first = timelineSegments.value[0];
  return first ? first.rangeText.split(' ~ ')[0] : '—';
});

/** 时间线终点文案 */
const timelineEndText = computed(() => {
  const last = timelineSegments.value[timelineSegments.value.length - 1];
  return last ? last.rangeText.split(' ~ ')[1] : '—';
});

/**
 * 金额格式化。
 * @param value 数值
 */
function formatAmount(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return '—';
  }
  return Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 });
}

/**
 * 百分比格式化。
 * @param value 数值（0-1）
 */
function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return '—';
  }
  return `${(Number(value) * 100).toFixed(2)}%`;
}

/**
 * 带符号百分比格式化（0-1）：正数带 +，负数带 -，零显示 0.00%。
 * 用于增幅类展示，避免出现「+-3.44%」「+(-2.81%)」这类歧义格式。
 * @param value 数值（0-1）
 */
function formatSignedPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return '—';
  }
  const pct = Number(value) * 100;
  const text = `${Math.abs(pct).toFixed(2)}%`;
  if (pct > 0) {
    return `+${text}`;
  }
  if (pct < 0) {
    return `-${text}`;
  }
  return text;
}

/**
 * 活动类型中文标签。
 * @param type 活动类型
 */
function typeLabel(type: string): string {
  return TYPE_LABELS[type] || type || '—';
}

/**
 * 活动状态中文标签。
 * @param status 活动状态
 */
function statusLabel(status: string): string {
  return STATUS_LABELS[status] || status || '—';
}

/**
 * 活动状态语义色。
 * @param status 活动状态
 */
function statusSeverity(status: string): string {
  return STATUS_SEVERITIES[status] || 'secondary';
}

/**
 * 影响等级中文标签。
 * @param level 影响等级
 */
function impactLabel(level: string): string {
  return IMPACT_LABELS[level] || level || '—';
}

/**
 * 影响等级语义色。
 * @param level 影响等级
 */
function impactSeverity(level: string): string {
  return IMPACT_SEVERITIES[level] || 'secondary';
}

/**
 * 置信度中文标签。
 * @param confidence 置信度
 */
function confidenceLabel(confidence: string): string {
  return CONFIDENCE_LABELS[confidence] || confidence || '—';
}

/**
 * 增幅来源中文标签。
 * @param source 来源标识
 */
function upliftSourceLabel(source: string): string {
  return UPLIFT_SOURCE_LABELS[source] || source || '—';
}

/**
 * 加载活动列表与预测对象（用于应用备选项兜底）。
 */
async function loadOptions(): Promise<void> {
  optionsLoading.value = true;
  optionsError.value = '';
  try {
    const [eventResult, objects] = await Promise.all([
      fetchEvents({ limit: 100 }),
      fetchEligibilityList({ limit: 100 }).catch(() => []),
    ]);
    eventList.value = eventResult.events;
    eventOptions.value = eventList.value.map((event) => ({
      label: `${event.event_name}（${formatBeijingDateTime(event.start_time)}）`,
      value: event.event_id,
    }));
    // 应用备选：优先活动 target_apps，空时回退预测对象应用列表
    const fallbackApps = Array.from(
      new Set(
        objects
          .filter((item) => item.status === 'eligible' || item.status === 'manually_included')
          .map((item) => item.app_name)
          .filter((name) => Boolean(name))
      )
    );
    fallbackAppNames.value = fallbackApps;
    if (!selectedEventId.value && eventOptions.value.length > 0) {
      selectedEventId.value = eventOptions.value[0].value;
    }
    rebuildAppOptions(fallbackApps);
  } catch (error) {
    optionsError.value = error instanceof Error ? error.message : '加载活动列表失败';
  } finally {
    optionsLoading.value = false;
  }
}

/**
 * 重建应用下拉选项。
 * @param fallbackApps 活动未标注影响应用时的备选应用列表（缺省用预测对象应用）
 */
function rebuildAppOptions(fallbackApps: string[] = fallbackAppNames.value): void {
  const event = selectedEvent.value;
  const apps = event && event.target_apps && event.target_apps.length > 0 ? event.target_apps : fallbackApps;
  const unique = Array.from(new Set(apps)).sort((a, b) => a.localeCompare(b, 'zh-CN'));
  appOptions.value = unique.map((name) => ({ label: name, value: name }));
  if (!appOptions.value.some((item) => item.value === selectedApp.value)) {
    selectedApp.value = appOptions.value.length > 0 ? appOptions.value[0].value : '';
  }
}

/** 活动切换：联动应用选项并清空结果 */
function handleEventChange(): void {
  rebuildAppOptions();
  result.value = null;
  renderAllCharts();
}

/**
 * 执行活动影响分析（活动专项预测）。
 */
async function loadAnalysis(): Promise<void> {
  if (!canAnalyze.value) {
    return;
  }
  analyzing.value = true;
  loadError.value = '';
  try {
    // 活动专项预测：force=true 允许对非 eligible 对象执行，结果保留风险标识
    result.value = await runForecast({
      app_name: selectedApp.value,
      uri_template: '',
      horizon: '24h',
      scenario: 'event_adjusted',
      include_interval: true,
      event_id: selectedEventId.value,
      force: true,
    });
    await nextTick();
    renderAllCharts();
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : '活动影响分析失败';
    result.value = null;
    renderAllCharts();
  } finally {
    analyzing.value = false;
  }
}

/**
 * 初始化（或获取已初始化的）图表实例。
 * @param chart 已有实例
 * @param el 容器元素
 */
function ensureChart(chart: EChartsType | null, el: HTMLElement | null): EChartsType | null {
  if (chart) {
    return chart;
  }
  if (!el) {
    return null;
  }
  return echarts.init(el);
}

/**
 * 渲染 ① vs 基线对比柱状图。
 */
function renderDiffChart1(): void {
  diffChart1 = ensureChart(diffChart1, diffChart1Ref.value);
  if (!diffChart1) {
    return;
  }
  const m1 = method1.value;
  if (!m1) {
    diffChart1.clear();
    return;
  }
  diffChart1.setOption(
    {
      grid: { left: 16, right: 16, top: 24, bottom: 8, containLabel: true },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      xAxis: {
        type: 'category',
        data: ['基线总量', '活动调整总量'],
        axisLabel: { color: '#5b6475', fontSize: 11 },
      },
      yAxis: {
        type: 'value',
        axisLabel: { color: '#5b6475', fontSize: 11 },
        splitLine: { lineStyle: { color: '#eef2f8' } },
      },
      series: [
        {
          type: 'bar',
          barWidth: 36,
          data: [
            { value: m1.total_baseline, itemStyle: { color: COLOR_BASELINE } },
            { value: m1.total_event_adjusted, itemStyle: { color: COLOR_ADJUSTED } },
          ],
        },
      ],
    } as never,
    true
  );
}

/**
 * 渲染 ③ 活动前后对比柱状图。
 */
function renderDiffChart3(): void {
  diffChart3 = ensureChart(diffChart3, diffChart3Ref.value);
  if (!diffChart3) {
    return;
  }
  const m3 = method3.value;
  if (!m3) {
    diffChart3.clear();
    return;
  }
  diffChart3.setOption(
    {
      grid: { left: 16, right: 16, top: 24, bottom: 8, containLabel: true },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      xAxis: {
        type: 'category',
        data: ['活动前基线', '预热期均值', '正式期均值', '回落期均值'],
        axisLabel: { color: '#5b6475', fontSize: 10, interval: 0 },
      },
      yAxis: {
        type: 'value',
        axisLabel: { color: '#5b6475', fontSize: 11 },
        splitLine: { lineStyle: { color: '#eef2f8' } },
      },
      series: [
        {
          type: 'bar',
          barWidth: 24,
          data: [
            { value: m3.pre_event_baseline, itemStyle: { color: COLOR_BASELINE } },
            { value: m3.preheat_avg, itemStyle: { color: COLOR_PREHEAT } },
            { value: m3.active_avg, itemStyle: { color: COLOR_ACTIVE } },
            { value: m3.cooldown_avg, itemStyle: { color: COLOR_COOLDOWN } },
          ],
        },
      ],
    } as never,
    true
  );
}

/**
 * 渲染三情景对比柱状图。
 */
function renderScenarioChart(): void {
  scenarioChart = ensureChart(scenarioChart, scenarioChartRef.value);
  if (!scenarioChart) {
    return;
  }
  const data = scenarios.value;
  if (!data || !data.available) {
    scenarioChart.clear();
    return;
  }
  const totals = SCENARIO_ROWS.map((row) => data.scenarios[row.key]?.total ?? 0);
  const increments = SCENARIO_ROWS.map((row) => data.scenarios[row.key]?.increment ?? 0);
  scenarioChart.setOption(
    {
      grid: { left: 16, right: 16, top: 32, bottom: 8, containLabel: true },
      legend: {
        data: ['预测总量', '活动增量'],
        top: 0,
        textStyle: { color: '#5b6475', fontSize: 12 },
      },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      xAxis: {
        type: 'category',
        data: SCENARIO_ROWS.map((row) => row.label),
        axisLabel: { color: '#5b6475', fontSize: 11 },
      },
      yAxis: {
        type: 'value',
        axisLabel: { color: '#5b6475', fontSize: 11 },
        splitLine: { lineStyle: { color: '#eef2f8' } },
      },
      series: [
        {
          name: '预测总量',
          type: 'bar',
          barWidth: 28,
          itemStyle: { color: COLOR_BASELINE },
          data: totals,
        },
        {
          name: '活动增量',
          type: 'bar',
          barWidth: 28,
          itemStyle: { color: COLOR_ADJUSTED },
          data: increments,
        },
      ],
    } as never,
    true
  );
}

/** 渲染全部图表 */
function renderAllCharts(): void {
  renderDiffChart1();
  renderDiffChart3();
  renderScenarioChart();
}

/** 窗口缩放时重绘图表 */
function handleResize(): void {
  diffChart1?.resize();
  diffChart3?.resize();
  scenarioChart?.resize();
}

onMounted(() => {
  window.addEventListener('resize', handleResize);
  loadOptions();
});

onUnmounted(() => {
  window.removeEventListener('resize', handleResize);
  diffChart1?.dispose();
  diffChart3?.dispose();
  scenarioChart?.dispose();
  diffChart1 = null;
  diffChart3 = null;
  scenarioChart = null;
});
</script>

<style scoped lang="scss">
.event-impact-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 24px;
  margin-bottom: 0;
}

.title-sub {
  margin: 0;
  font-size: 13px;
  color: var(--muted);
  max-width: 760px;
  line-height: 1.6;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.mock-banner {
  width: 100%;
}

.mock-banner-content {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 13px;
}

.mock-banner-tag {
  font-weight: 700;
}

.filter-card {
  padding: 16px 20px;
}

.filter-toolbar {
  display: flex;
  align-items: flex-end;
  gap: 16px;
  flex-wrap: wrap;
}

.filter-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 220px;
}

.filter-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--muted);
}

.filter-dropdown {
  min-width: 220px;
}

.filter-spacer {
  flex: 1;
  min-width: 0;
}

.filter-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.filter-summary {
  margin-top: 12px;
  font-size: 12px;
  color: var(--muted);
}

.event-info-card {
  padding: 18px 20px 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.event-info-tags {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.event-info-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.event-info-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: rgba(var(--primary-color-rgb), 0.03);
}

.event-info-label {
  font-size: 12px;
  color: var(--muted);
}

.event-info-value {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  word-break: break-all;
  line-height: 1.5;
}

.section-title {
  display: flex;
  align-items: baseline;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.section-title-chip {
  font-size: 15px;
  font-weight: 750;
  color: var(--text);
}

.section-title-hint {
  font-size: 12px;
  color: var(--muted);
}

.diff-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.diff-card {
  padding: 16px 18px 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.diff-card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.diff-index {
  width: 24px;
  height: 24px;
  border-radius: 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
  background: rgba(var(--primary-color-rgb), 0.1);
  color: var(--primary);
}

.diff-name {
  font-size: 13px;
  font-weight: 700;
  color: var(--text);
}

.diff-badge {
  margin-left: auto;
}

.diff-chart {
  width: 100%;
  height: 200px;
}

.diff-metrics {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.diff-metrics-full {
  min-height: 200px;
  justify-content: center;
}

.diff-metric-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  font-size: 12px;

  span:first-child {
    color: var(--muted);
  }

  span:last-child {
    color: var(--text);
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }
}

.diff-note {
  margin-top: 4px;
  font-size: 12px;
  color: var(--muted);
  line-height: 1.6;
}

.diff-unavailable {
  min-height: 200px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  font-size: 12px;
  color: var(--muted);
  text-align: center;
  line-height: 1.6;
  padding: 0 8px;
}

.diff-empty {
  min-height: 200px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  color: var(--muted);
}

.scenario-card {
  padding: 18px 20px 20px;
}

.scenario-body {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr);
  gap: 20px;
  align-items: center;
}

.scenario-chart {
  width: 100%;
  height: 280px;
}

.scenario-table-wrap {
  overflow-x: auto;
}

.scenario-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;

  th,
  td {
    padding: 10px 12px;
    border-bottom: 1px solid var(--border);
    text-align: left;
    white-space: nowrap;
    color: var(--text);
    font-variant-numeric: tabular-nums;
  }

  th {
    color: var(--muted);
    font-weight: 600;
  }
}

.scenario-unavailable {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 20px 0;
  font-size: 12px;
  color: var(--muted);
}

.summary-empty {
  padding: 24px 0;
  text-align: center;
  font-size: 13px;
  color: var(--muted);
}

.timeline-card {
  padding: 18px 20px 20px;
}

.timeline-legend {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--muted);
}

.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 3px;
  display: inline-block;

  &.preheat {
    background: rgba(59, 130, 246, 0.5);
  }

  &.active {
    background: rgba(245, 158, 11, 0.6);
  }

  &.cooldown {
    background: rgba(16, 185, 129, 0.5);
  }
}

.timeline-track {
  display: flex;
  align-items: stretch;
  width: 100%;
  height: 44px;
  border-radius: 12px;
  overflow: hidden;
  border: 1px solid var(--border);
}

.timeline-segment {
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 0;
  overflow: hidden;

  &.preheat {
    background: rgba(59, 130, 246, 0.18);
    color: #1d4ed8;
  }

  &.active {
    background: rgba(245, 158, 11, 0.24);
    color: #b45309;
  }

  &.cooldown {
    background: rgba(16, 185, 129, 0.18);
    color: #047857;
  }
}

.timeline-segment-label {
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.timeline-axis {
  display: flex;
  justify-content: space-between;
  margin-top: 8px;
  font-size: 11px;
  color: var(--muted);
}

.timeline-details {
  display: flex;
  align-items: center;
  gap: 20px;
  flex-wrap: wrap;
  margin-top: 14px;
}

.timeline-detail {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.timeline-detail-dot {
  width: 10px;
  height: 10px;
  border-radius: 3px;
  display: inline-block;

  &.preheat {
    background: rgba(59, 130, 246, 0.5);
  }

  &.active {
    background: rgba(245, 158, 11, 0.6);
  }

  &.cooldown {
    background: rgba(16, 185, 129, 0.5);
  }
}

.timeline-detail-label {
  font-weight: 600;
  color: var(--text);
}

.timeline-detail-range {
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

@media (max-width: 1200px) {
  .event-info-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .scenario-body {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 768px) {
  .diff-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .event-info-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
