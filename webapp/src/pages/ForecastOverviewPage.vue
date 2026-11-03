<template>
  <div class="forecast-overview-page">
    <header class="page-header">
      <div class="page-title">
        <span class="title-chip">交易量预测总览</span>
        <p class="title-sub">
          查看应用 / 接口的交易量预测曲线、预测区间与活动影响，支持常规基线与活动调整两种场景，时间统一按北京时间（UTC+8）展示。
        </p>
      </div>
      <div class="header-actions">
        <Button
          label="重新预测"
          icon="pi pi-refresh"
          outlined
          :loading="predicting"
          :disabled="!canQuery"
          @click="loadForecast"
        />
      </div>
    </header>

    <Message v-if="isMockData" severity="warn" :closable="false" class="mock-banner">
      <div class="mock-banner-content">
        <Tag value="Mock" severity="warn" class="mock-banner-tag" />
        <span>当前为 Mock 演示数据，不可用于生产报告。</span>
        <span v-if="historyRangeText" class="mock-banner-meta">训练数据范围：{{ historyRangeText }}</span>
      </div>
    </Message>

    <Message v-if="loadError" severity="error" :closable="false" class="mock-banner">
      <div class="mock-banner-content">
        <span>{{ loadError }}</span>
        <Button label="重试" icon="pi pi-refresh" text size="small" :disabled="!canQuery" @click="loadForecast" />
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
          <label class="filter-label" for="overview-app-filter">应用名称</label>
          <Dropdown
            v-model="selectedApp"
            inputId="overview-app-filter"
            class="filter-dropdown"
            :options="appOptions"
            optionLabel="label"
            optionValue="value"
            placeholder="请选择应用"
            :loading="optionsLoading"
            showClear
            @change="handleAppChange"
          />
        </div>
        <div class="filter-field">
          <label class="filter-label" for="overview-uri-filter">URI 模板</label>
          <Dropdown
            v-model="selectedUri"
            inputId="overview-uri-filter"
            class="filter-dropdown"
            :options="uriOptions"
            optionLabel="label"
            optionValue="value"
            placeholder="应用级汇总"
            :disabled="!selectedApp"
            showClear
          />
        </div>
        <div class="filter-field">
          <label class="filter-label" for="overview-horizon-filter">预测时长</label>
          <Dropdown
            v-model="horizon"
            inputId="overview-horizon-filter"
            class="filter-dropdown filter-dropdown-short"
            :options="horizonOptions"
            optionLabel="label"
            optionValue="value"
          />
        </div>
        <div class="filter-field">
          <label class="filter-label" for="overview-scenario-filter">场景</label>
          <Dropdown
            v-model="scenario"
            inputId="overview-scenario-filter"
            class="filter-dropdown filter-dropdown-short"
            :options="scenarioOptions"
            optionLabel="label"
            optionValue="value"
            @change="handleScenarioChange"
          />
        </div>
        <div v-if="scenario === 'event_adjusted'" class="filter-field">
          <label class="filter-label" for="overview-event-filter">业务活动</label>
          <Dropdown
            v-model="selectedEventId"
            inputId="overview-event-filter"
            class="filter-dropdown"
            :options="eventOptions"
            optionLabel="label"
            optionValue="value"
            placeholder="请选择活动"
            :loading="optionsLoading"
            showClear
          />
        </div>
        <div class="filter-spacer"></div>
        <div class="filter-actions">
          <Button
            label="查询预测"
            icon="pi pi-search"
            :loading="predicting"
            :disabled="!canQuery"
            @click="loadForecast"
          />
        </div>
      </div>
      <div class="filter-summary">
        预测曲线含基线 / 活动调整 / 历史实际值三条曲线与置信区间；活动调整场景下额外标注预热期 / 正式期 / 回落期。
      </div>
    </section>

    <!-- 统计卡片 -->
    <section class="stat-grid">
      <div class="card stat-card total" data-anim>
        <div class="stat-card-head">
          <span class="stat-card-icon"><i class="ri-calculator-line"></i></span>
          <span class="stat-card-label">预测总量</span>
        </div>
        <div class="stat-card-value">{{ statTotalText }}</div>
        <div class="stat-card-foot">
          {{ hasEvent ? `活动增量 ${statIncrementText}` : '常规基线口径' }}
        </div>
      </div>
      <div class="card stat-card peak" data-anim>
        <div class="stat-card-head">
          <span class="stat-card-icon"><i class="ri-arrow-up-circle-line"></i></span>
          <span class="stat-card-label">峰值</span>
        </div>
        <div class="stat-card-value">{{ statPeakText }}</div>
        <div class="stat-card-foot">{{ statPeakTimeText }}</div>
      </div>
      <div class="card stat-card qps" data-anim>
        <div class="stat-card-head">
          <span class="stat-card-icon"><i class="ri-speed-up-line"></i></span>
          <span class="stat-card-label">平均 QPS</span>
        </div>
        <div class="stat-card-value">{{ statQpsText }}</div>
        <div class="stat-card-foot">按预测窗口均值估算</div>
      </div>
      <div class="card stat-card model" data-anim>
        <div class="stat-card-head">
          <span class="stat-card-icon"><i class="ri-brain-line"></i></span>
          <span class="stat-card-label">模型</span>
        </div>
        <div class="stat-card-value stat-card-value-text">{{ statModelText }}</div>
        <div class="stat-card-foot">{{ statEligibilityText }}</div>
      </div>
      <div class="card stat-card source" data-anim>
        <div class="stat-card-head">
          <span class="stat-card-icon"><i class="ri-database-2-line"></i></span>
          <span class="stat-card-label">数据来源</span>
        </div>
        <div class="stat-card-value stat-card-value-tag">
          <Tag v-if="result" :value="dataSourceLabel" :severity="dataSourceSeverity" />
          <span v-else class="stat-card-value-empty">—</span>
        </div>
        <div class="stat-card-foot">{{ statForecastIdText }}</div>
      </div>
    </section>

    <!-- 核心图表 -->
    <section class="card chart-card" data-anim>
      <div class="card-header">
        <div class="card-title">
          <span class="card-icon blue"><i class="ri-line-chart-line"></i></span>
          交易量预测曲线
        </div>
        <div v-if="phaseLegend.length > 0" class="phase-legend">
          <span v-for="item in phaseLegend" :key="`phase-${item.key}`" class="legend-item">
            <i class="legend-dot" :style="{ background: item.color }"></i>{{ item.label }}
          </span>
        </div>
      </div>
      <div ref="mainChartRef" class="main-chart"></div>
      <div v-if="!result && !predicting" class="chart-empty">
        {{ selectedApp ? '暂无预测结果，点击「查询预测」开始' : '请先选择应用名称' }}
      </div>
    </section>

    <!-- 摘要面板 -->
    <section class="card summary-card" data-anim>
      <div class="card-header">
        <div class="card-title">
          <span class="card-icon orange"><i class="ri-file-text-line"></i></span>
          预测摘要
        </div>
        <Button
          v-if="result"
          label="加载回测指标"
          icon="pi pi-chart-bar"
          text
          size="small"
          :loading="evaluationLoading"
          :disabled="!selectedApp"
          @click="loadEvaluation"
        />
      </div>

      <div v-if="result" class="summary-body">
        <div class="summary-grid">
          <div class="summary-item">
            <span class="summary-item-label">基线预测总量</span>
            <span class="summary-item-value">{{ formatAmount(result.summary.total_baseline) }}</span>
          </div>
          <div class="summary-item">
            <span class="summary-item-label">活动调整总量</span>
            <span class="summary-item-value">{{ formatAmount(result.summary.total_event_adjusted) }}</span>
          </div>
          <div class="summary-item">
            <span class="summary-item-label">活动增量</span>
            <span class="summary-item-value">{{ formatAmount(result.summary.total_event_increment) }}</span>
          </div>
          <div class="summary-item">
            <span class="summary-item-label">增量占比</span>
            <span class="summary-item-value">{{ upliftRatioText }}</span>
          </div>
          <div class="summary-item">
            <span class="summary-item-label">基线峰值</span>
            <span class="summary-item-value">{{ formatAmount(result.summary.peak_baseline) }}</span>
          </div>
          <div class="summary-item">
            <span class="summary-item-label">调整峰值</span>
            <span class="summary-item-value">{{ formatAmount(result.summary.peak_event_adjusted) }}</span>
          </div>
          <div class="summary-item">
            <span class="summary-item-label">峰值时间</span>
            <span class="summary-item-value">{{ formatBeijingDateTime(result.summary.peak_timestamp) }}</span>
          </div>
          <div class="summary-item">
            <span class="summary-item-label">预测场景</span>
            <span class="summary-item-value">{{ scenarioLabel(result.scenario) }}</span>
          </div>
        </div>

        <div class="summary-block">
          <div class="summary-block-title">风险标识</div>
          <div v-if="riskFlagList.length > 0" class="risk-flag-list">
            <Tag
              v-for="(flag, index) in riskFlagList"
              :key="`risk-${index}`"
              :value="flag"
              severity="warn"
              class="risk-flag-tag"
            />
          </div>
          <div v-else class="summary-muted">无风险标识</div>
        </div>

        <div class="summary-block">
          <div class="summary-block-title">回测指标</div>
          <div v-if="evaluationLoading" class="summary-muted">回测计算中，请稍候…</div>
          <div v-else-if="evaluationError" class="summary-error">{{ evaluationError }}</div>
          <div v-else-if="evaluationRows.length > 0" class="eval-table-wrap">
            <table class="eval-table">
              <thead>
                <tr>
                  <th>模型</th>
                  <th>MAE</th>
                  <th>WAPE</th>
                  <th>sMAPE</th>
                  <th>区间覆盖率</th>
                  <th>相对基线改善</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in evaluationRows" :key="`eval-${row.strategy}`">
                  <td>{{ modelLabel(row.strategy) }}</td>
                  <td>{{ formatMetric(row.mae) }}</td>
                  <td>{{ formatPercentMetric(row.wape) }}</td>
                  <td>{{ formatPercentMetric(row.smape) }}</td>
                  <td>{{ formatPercentMetric(row.coverage) }}</td>
                  <td>{{ formatPercentMetric(row.improvement) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-else class="summary-muted">点击右上角「加载回测指标」按需计算（耗时较长）。</div>
        </div>

        <div v-if="isMockData" class="summary-block summary-mock">
          <Tag value="Mock" severity="warn" />
          <span>本次预测基于 Mock 演示数据生成，结果仅供功能演示，不可用于生产决策。</span>
        </div>
      </div>
      <div v-else class="summary-empty">暂无预测摘要，请先选择应用并执行预测。</div>
    </section>
  </div>
</template>

<script setup lang="ts">
/**
 * 交易量预测总览页（阶段六交付物）。
 * 展示常规基线 / 活动调整预测曲线、预测区间、活动阶段标识与摘要信息。
 * 页面文案全部为中文硬编码，时间统一按北京时间（UTC+8）展示。
 */
import { computed, onMounted, onUnmounted, ref } from 'vue';
import * as echarts from 'echarts';
import type { EChartsType } from 'echarts/core';
import Button from 'primevue/button';
import Dropdown from 'primevue/dropdown';
import Message from 'primevue/message';
import Tag from 'primevue/tag';
import {
  fetchEligibilityList,
  fetchForecastEvaluation,
  fetchHistorySeries,
  runForecast,
} from '@/api/forecast';
import type {
  ForecastEvaluationResult,
  ForecastEligibilityObject,
  ForecastPoint,
  ForecastPredictResult,
  HistorySeriesPoint,
} from '@/api/forecast';
import { fetchEvents } from '@/api/events';
import type { BusinessEvent } from '@/api/events';
import { formatBeijingDateTime, parseTimestamp, toBeijingParts } from '@/utils';

/** 预测时长选项 */
const horizonOptions = [
  { label: '未来 24 小时', value: '24h' },
  { label: '未来 7 天', value: '7d' },
];

/** 预测场景选项 */
const scenarioOptions = [
  { label: '常规基线', value: 'baseline' },
  { label: '活动调整', value: 'event_adjusted' },
];

/** 场景中文标签 */
const SCENARIO_LABELS: Record<string, string> = {
  baseline: '常规基线',
  event_adjusted: '活动调整',
  scenario_compare: '多情景对比',
};

/** 模型中文标签 */
const MODEL_LABELS: Record<string, string> = {
  lightgbm: 'LightGBM',
  seasonal_naive: '季节朴素',
  ets: 'ETS',
  sarima: 'SARIMA',
};

/** 活动阶段中文标签 */
const PHASE_LABELS: Record<string, string> = {
  preheat: '预热期',
  active: '正式期',
  cooldown: '回落期',
};

/** 活动阶段底色（markArea 三种不同底色） */
const PHASE_COLORS: Record<string, string> = {
  preheat: 'rgba(59, 130, 246, 0.12)',
  active: 'rgba(245, 158, 11, 0.16)',
  cooldown: 'rgba(16, 185, 129, 0.12)',
};

/** 图表曲线配色 */
const COLOR_BASELINE = '#1d6bff';
const COLOR_ADJUSTED = '#f97316';
const COLOR_ACTUAL = '#94a3b8';
const COLOR_BAND = 'rgba(29, 107, 255, 0.12)';

/** 全量拉取上限 */
const LIST_LIMIT = 1000;

const appOptions = ref<Array<{ label: string; value: string }>>([]);
const uriOptions = ref<Array<{ label: string; value: string }>>([]);
const eventOptions = ref<Array<{ label: string; value: string }>>([]);
const eligibilityObjects = ref<ForecastEligibilityObject[]>([]);
const eventList = ref<BusinessEvent[]>([]);

const selectedApp = ref<string>('');
const selectedUri = ref<string>('');
const horizon = ref<string>('24h');
const scenario = ref<string>('baseline');
const selectedEventId = ref<string>('');

const optionsLoading = ref(false);
const optionsError = ref('');
const predicting = ref(false);
const loadError = ref('');
const result = ref<ForecastPredictResult | null>(null);
const historyPoints = ref<HistorySeriesPoint[]>([]);

const evaluationLoading = ref(false);
const evaluationError = ref('');
const evaluationData = ref<ForecastEvaluationResult | null>(null);

const mainChartRef = ref<HTMLElement | null>(null);
let mainChart: EChartsType | null = null;

/** 是否可发起预测查询 */
const canQuery = computed(() => Boolean(selectedApp.value) && !predicting.value);

/** 是否存在活动影响 */
const hasEvent = computed(() => {
  const info = result.value?.event;
  return Boolean(info && info.event_id);
});

/** 是否 Mock 数据 */
const isMockData = computed(() => {
  if (!result.value) {
    return false;
  }
  return String(result.value.data_source || '').toLowerCase() === 'mock';
});

/** 数据来源标签 */
const dataSourceLabel = computed(() => (isMockData.value ? 'Mock 演示数据' : '真实数据'));

/** 数据来源语义色 */
const dataSourceSeverity = computed(() => (isMockData.value ? 'warn' : 'success'));

/** 训练数据范围文案 */
const historyRangeText = computed(() => {
  const range = result.value?.history_range;
  if (!range || !range.start || !range.end) {
    return '';
  }
  return `${formatBeijingDateTime(range.start)} ~ ${formatBeijingDateTime(range.end)}`;
});

/** 统计卡片：预测总量 */
const statTotalText = computed(() =>
  result.value ? formatAmount(result.value.summary.total_event_adjusted) : '—'
);

/** 统计卡片：活动增量 */
const statIncrementText = computed(() =>
  result.value ? formatAmount(result.value.summary.total_event_increment) : '—'
);

/** 统计卡片：峰值 */
const statPeakText = computed(() =>
  result.value ? formatAmount(result.value.summary.peak_event_adjusted) : '—'
);

/** 统计卡片：峰值时间 */
const statPeakTimeText = computed(() =>
  result.value ? formatBeijingDateTime(result.value.summary.peak_timestamp) : '暂无预测结果'
);

/** 统计卡片：平均 QPS */
const statQpsText = computed(() =>
  result.value ? formatNumber(result.value.summary.avg_qps, 2) : '—'
);

/** 统计卡片：模型名 */
const statModelText = computed(() =>
  result.value ? modelLabel(result.value.model) : '—'
);

/** 统计卡片：资格说明 */
const statEligibilityText = computed(() => {
  const eligibility = result.value?.eligibility;
  if (!eligibility || !eligibility.status) {
    return '暂无资格评估信息';
  }
  const score = eligibility.score != null ? `（评分 ${eligibility.score}）` : '';
  return `预测资格：${eligibility.status}${score}`;
});

/** 统计卡片：预测 ID */
const statForecastIdText = computed(() =>
  result.value ? `预测编号 ${result.value.forecast_id}` : '暂无预测结果'
);

/** 增量占比文案 */
const upliftRatioText = computed(() => {
  const summary = result.value?.summary;
  if (!summary || !summary.total_baseline) {
    return '—';
  }
  const ratio = summary.total_event_increment / summary.total_baseline;
  return `${(ratio * 100).toFixed(2)}%`;
});

/** 风险标识列表 */
const riskFlagList = computed(() => {
  const flags = result.value?.risk_flags;
  return Array.isArray(flags) ? flags.filter((flag) => Boolean(flag)) : [];
});

/** 图表活动阶段图例 */
const phaseLegend = computed(() => {
  const phases = new Set<string>();
  (result.value?.points || []).forEach((point) => {
    if (point.event_phase && point.event_phase !== 'none') {
      phases.add(point.event_phase);
    }
  });
  return Array.from(phases).map((key) => ({
    key,
    label: PHASE_LABELS[key] || key,
    color: PHASE_COLORS[key] || 'rgba(148, 163, 184, 0.2)',
  }));
});

/** 回测指标表格行 */
const evaluationRows = computed(() => {
  const backtest = evaluationData.value?.backtest || {};
  return Object.keys(backtest).map((strategy) => {
    const metrics = backtest[strategy] || {};
    return {
      strategy,
      mae: metrics.mae,
      wape: metrics.wape,
      smape: metrics.smape,
      coverage: metrics.coverage,
      improvement: metrics.improvement_vs_baseline ?? metrics.improvement,
    };
  });
});

/**
 * 金额 / 数量千分位格式化。
 * @param value 数值
 */
function formatAmount(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return '—';
  }
  return Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 });
}

/**
 * 通用数字格式化。
 * @param value 数值
 * @param digits 小数位
 */
function formatNumber(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return '—';
  }
  return Number(value).toFixed(digits);
}

/**
 * 回测指标格式化。
 * @param value 数值
 */
function formatMetric(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === '') {
    return '—';
  }
  const num = Number(value);
  return Number.isNaN(num) ? String(value) : num.toFixed(2);
}

/**
 * 回测百分比类指标格式化（WAPE / sMAPE / 覆盖率 / 改善度）。
 * @param value 数值（0-1 或百分数）
 */
function formatPercentMetric(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === '') {
    return '—';
  }
  const num = Number(value);
  if (Number.isNaN(num)) {
    return String(value);
  }
  return `${(num * 100).toFixed(2)}%`;
}

/**
 * 模型中文标签。
 * @param model 模型标识
 */
function modelLabel(model: string): string {
  return MODEL_LABELS[model] || model || '—';
}

/**
 * 场景中文标签。
 * @param value 场景值
 */
function scenarioLabel(value: string): string {
  return SCENARIO_LABELS[value] || value || '—';
}

/**
 * 图表横轴时间格式化（北京时间，紧凑格式 MM-dd HH:mm）。
 * @param ms 时间戳（毫秒）
 */
function formatAxisTime(ms: number): string {
  const parts = toBeijingParts(ms);
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${pad(parts.month)}-${pad(parts.day)} ${pad(parts.hour)}:${pad(parts.minute)}`;
}

/**
 * 加载筛选项：预测对象（eligible + 人工纳入）与活动列表。
 */
async function loadOptions(): Promise<void> {
  optionsLoading.value = true;
  optionsError.value = '';
  try {
    const [objects, eventResult] = await Promise.all([
      fetchEligibilityList({ limit: LIST_LIMIT }),
      fetchEvents({ limit: LIST_LIMIT }),
    ]);
    eligibilityObjects.value = objects.filter(
      (item) => item.status === 'eligible' || item.status === 'manually_included'
    );
    eventList.value = eventResult.events;
    rebuildAppOptions();
    rebuildEventOptions();
    if (!selectedApp.value && appOptions.value.length > 0) {
      selectedApp.value = appOptions.value[0].value;
      rebuildUriOptions();
      await loadForecast();
    }
  } catch (error) {
    optionsError.value = error instanceof Error ? error.message : '加载筛选项失败';
  } finally {
    optionsLoading.value = false;
  }
}

/** 重建应用下拉选项 */
function rebuildAppOptions(): void {
  const names = Array.from(
    new Set(eligibilityObjects.value.map((item) => item.app_name).filter((name) => Boolean(name)))
  );
  names.sort((a, b) => a.localeCompare(b, 'zh-CN'));
  appOptions.value = names.map((name) => ({ label: name, value: name }));
}

/** 重建活动下拉选项 */
function rebuildEventOptions(): void {
  eventOptions.value = eventList.value.map((event) => ({
    label: `${event.event_name}（${formatBeijingDateTime(event.start_time)}）`,
    value: event.event_id,
  }));
}

/** 重建 URI 下拉选项（跟随当前应用） */
function rebuildUriOptions(): void {
  const uris = eligibilityObjects.value
    .filter((item) => item.app_name === selectedApp.value)
    .map((item) => item.uri_template || '');
  const unique = Array.from(new Set(uris));
  uriOptions.value = unique.map((uri) => ({
    label: uri || '应用级汇总（全部 URL）',
    value: uri,
  }));
  if (!uriOptions.value.some((item) => item.value === selectedUri.value)) {
    selectedUri.value = '';
  }
}

/** 应用切换：联动 URI 选项并清空结果 */
function handleAppChange(): void {
  rebuildUriOptions();
  result.value = null;
  historyPoints.value = [];
  evaluationData.value = null;
}

/** 场景切换：切回常规基线时清空活动选择 */
function handleScenarioChange(): void {
  if (scenario.value === 'baseline') {
    selectedEventId.value = '';
  }
}

/**
 * 执行预测：并行拉取预测结果与历史实际值。
 */
async function loadForecast(): Promise<void> {
  if (!selectedApp.value || predicting.value) {
    return;
  }
  predicting.value = true;
  loadError.value = '';
  const isEventScenario = scenario.value === 'event_adjusted';
  const eventId = isEventScenario ? selectedEventId.value : '';
  if (isEventScenario && !eventId) {
    predicting.value = false;
    loadError.value = '活动调整场景需先选择业务活动';
    return;
  }
  try {
    const historyHours = horizon.value === '7d' ? 168 : 24;
    const [predictResult, historyResult] = await Promise.all([
      runForecast({
        app_name: selectedApp.value,
        uri_template: selectedUri.value,
        horizon: horizon.value,
        scenario: scenario.value,
        include_interval: true,
        event_id: eventId,
        // 活动专项预测允许强制执行（结果保留风险标识）
        force: isEventScenario,
      }),
      fetchHistorySeries({
        app_name: selectedApp.value,
        uri_template: selectedUri.value,
        hours: historyHours,
      }).catch(() => ({
        points: [] as HistorySeriesPoint[],
      })),
    ]);
    result.value = predictResult;
    historyPoints.value = historyResult.points || [];
    evaluationData.value = null;
    evaluationError.value = '';
    renderChart();
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : '预测失败';
    result.value = null;
    historyPoints.value = [];
    renderChart();
  } finally {
    predicting.value = false;
  }
}

/**
 * 按需加载回测指标。
 */
async function loadEvaluation(): Promise<void> {
  if (!selectedApp.value || evaluationLoading.value) {
    return;
  }
  evaluationLoading.value = true;
  evaluationError.value = '';
  try {
    evaluationData.value = await fetchForecastEvaluation({
      app_name: selectedApp.value,
      uri_template: selectedUri.value,
      horizon: horizon.value,
    });
  } catch (error) {
    evaluationError.value = error instanceof Error ? error.message : '回测指标加载失败';
  } finally {
    evaluationLoading.value = false;
  }
}

/**
 * 计算活动阶段 markArea 片段（连续同阶段合并）。
 * @param points 预测点列表
 */
function buildPhaseSegments(points: ForecastPoint[]): Array<{ phase: string; start: number; end: number }> {
  const segments: Array<{ phase: string; start: number; end: number }> = [];
  let current: { phase: string; start: number; end: number } | null = null;
  points.forEach((point) => {
    const ts = parseTimestamp(point.timestamp);
    const phase = point.event_phase || '';
    if (ts === null || !phase || phase === 'none') {
      if (current) {
        segments.push(current);
        current = null;
      }
      return;
    }
    if (current && current.phase === phase) {
      current.end = ts;
    } else {
      if (current) {
        segments.push(current);
      }
      current = { phase, start: ts, end: ts };
    }
  });
  if (current) {
    segments.push(current);
  }
  return segments;
}

/**
 * 渲染核心预测曲线图。
 */
function renderChart(): void {
  if (!mainChart) {
    return;
  }
  const points = result.value?.points || [];
  const actualPoints = historyPoints.value || [];

  const lowerData: Array<[number, number]> = [];
  const bandData: Array<[number, number]> = [];
  const baselineData: Array<[number, number]> = [];
  const adjustedData: Array<[number, number]> = [];
  const pointByTs = new Map<number, ForecastPoint>();
  points.forEach((point) => {
    const ts = parseTimestamp(point.timestamp);
    if (ts === null) {
      return;
    }
    pointByTs.set(ts, point);
    lowerData.push([ts, point.lower_bound]);
    bandData.push([ts, Math.max(point.upper_bound - point.lower_bound, 0)]);
    baselineData.push([ts, point.baseline_forecast]);
    adjustedData.push([ts, point.event_adjusted_forecast]);
  });

  const actualData: Array<[number, number]> = [];
  const actualByTs = new Map<number, number>();
  actualPoints.forEach((point) => {
    const ts = parseTimestamp(point.timestamp);
    if (ts === null) {
      return;
    }
    actualByTs.set(ts, point.actual);
    actualData.push([ts, point.actual]);
  });

  const showAdjusted = points.some(
    (point) => Math.abs(point.event_adjusted_forecast - point.baseline_forecast) > 1e-6
  );

  const phaseSegments = buildPhaseSegments(points);
  const markAreaData = phaseSegments.map((segment) => [
    {
      name: PHASE_LABELS[segment.phase] || segment.phase,
      xAxis: segment.start,
      itemStyle: { color: PHASE_COLORS[segment.phase] || 'rgba(148, 163, 184, 0.2)' },
    },
    { xAxis: segment.end },
  ]);

  const series: unknown[] = [
    {
      name: '区间下界',
      type: 'line',
      stack: 'forecast-band',
      silent: true,
      showSymbol: false,
      lineStyle: { opacity: 0 },
      data: lowerData,
      z: 1,
    },
    {
      name: '预测区间',
      type: 'line',
      stack: 'forecast-band',
      silent: true,
      showSymbol: false,
      lineStyle: { opacity: 0 },
      areaStyle: { color: COLOR_BAND },
      data: bandData,
      z: 1,
    },
    {
      name: '基线预测',
      type: 'line',
      showSymbol: false,
      smooth: true,
      lineStyle: { width: 2, color: COLOR_BASELINE },
      itemStyle: { color: COLOR_BASELINE },
      data: baselineData,
      z: 3,
      markArea: markAreaData.length > 0 ? { silent: true, data: markAreaData } : undefined,
    },
    {
      name: '历史实际值',
      type: 'line',
      showSymbol: false,
      smooth: true,
      lineStyle: { width: 2, type: 'dashed', color: COLOR_ACTUAL },
      itemStyle: { color: COLOR_ACTUAL },
      data: actualData,
      z: 2,
    },
  ];

  if (showAdjusted) {
    series.push({
      name: '活动调整预测',
      type: 'line',
      showSymbol: false,
      smooth: true,
      lineStyle: { width: 2, color: COLOR_ADJUSTED },
      itemStyle: { color: COLOR_ADJUSTED },
      data: adjustedData,
      z: 4,
    });
  }

  const option = {
    animation: true,
    grid: {
      left: 16,
      right: 24,
      top: 48,
      bottom: 16,
      containLabel: true,
    },
    legend: {
      data: showAdjusted
        ? ['基线预测', '活动调整预测', '历史实际值', '预测区间']
        : ['基线预测', '历史实际值', '预测区间'],
      top: 8,
      textStyle: { color: '#5b6475', fontSize: 12 },
    },
    tooltip: {
      trigger: 'axis',
      confine: true,
      axisPointer: { type: 'line' },
      formatter(params: unknown) {
        const list = Array.isArray(params) ? params : [];
        const first = list[0] as { axisValue?: unknown; value?: unknown };
        const rawTs = Number(
          first?.axisValue ?? (Array.isArray(first?.value) ? (first.value as unknown[])[0] : NaN)
        );
        const point = pointByTs.get(rawTs);
        const actual = actualByTs.get(rawTs);
        const rows: string[] = [`<div>${formatBeijingDateTime(rawTs)}</div>`];
        if (point) {
          rows.push(
            `<div>基线预测：${formatAmount(point.baseline_forecast)}</div>`
          );
          if (showAdjusted) {
            rows.push(
              `<div>活动调整：${formatAmount(point.event_adjusted_forecast)}</div>`,
              `<div>活动增量：${formatAmount(point.event_increment)}</div>`
            );
          }
          rows.push(
            `<div>预测区间：${formatAmount(point.lower_bound)} ~ ${formatAmount(point.upper_bound)}</div>`
          );
          if (point.event_phase && point.event_phase !== 'none') {
            rows.push(`<div>活动阶段：${PHASE_LABELS[point.event_phase] || point.event_phase}</div>`);
          }
        }
        if (actual !== undefined) {
          rows.push(`<div>历史实际值：${formatAmount(actual)}</div>`);
        }
        return rows.join('');
      },
    },
    xAxis: {
      type: 'time',
      axisLabel: {
        color: '#5b6475',
        fontSize: 11,
        formatter: (value: number) => formatAxisTime(value),
      },
      axisLine: { lineStyle: { color: '#e1e7f0' } },
      splitLine: { show: true, lineStyle: { color: '#eef2f8' } },
    },
    yAxis: {
      type: 'value',
      name: '交易量',
      nameTextStyle: { color: '#5b6475' },
      axisLabel: { color: '#5b6475', fontSize: 11 },
      splitLine: { lineStyle: { color: '#eef2f8' } },
    },
    series,
  };

  mainChart.setOption(option as never, true);
}

/** 窗口缩放时重绘图表 */
function handleResize(): void {
  mainChart?.resize();
}

onMounted(() => {
  if (mainChartRef.value) {
    mainChart = echarts.init(mainChartRef.value);
  }
  window.addEventListener('resize', handleResize);
  loadOptions();
});

onUnmounted(() => {
  window.removeEventListener('resize', handleResize);
  mainChart?.dispose();
  mainChart = null;
});
</script>

<style scoped lang="scss">
.forecast-overview-page {
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
  max-width: 720px;
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

.mock-banner-meta {
  color: var(--muted);
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
  min-width: 200px;
}

.filter-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--muted);
}

.filter-dropdown {
  min-width: 200px;
}

.filter-dropdown-short {
  min-width: 150px;
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

.stat-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 16px;
}

.stat-card {
  padding: 18px 20px;
}

.stat-card-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.stat-card-icon {
  width: 32px;
  height: 32px;
  border-radius: 10px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  background: rgba(var(--primary-color-rgb), 0.1);
  color: var(--primary);
}

.stat-card-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--muted);
}

.stat-card-value {
  font-size: 26px;
  font-weight: 750;
  line-height: 1.1;
  color: var(--text);
  word-break: break-all;
}

.stat-card-value-text {
  font-size: 20px;
  padding-top: 4px;
}

.stat-card-value-tag {
  padding-top: 4px;
}

.stat-card-value-empty {
  font-size: 20px;
  color: var(--muted);
}

.stat-card-foot {
  margin-top: 6px;
  font-size: 12px;
  color: var(--muted);
  word-break: break-all;
}

.stat-card.total .stat-card-icon {
  background: rgba(29, 107, 255, 0.12);
  color: var(--primary);
}

.stat-card.peak .stat-card-icon {
  background: rgba(249, 115, 22, 0.14);
  color: #ea580c;
}

.stat-card.qps .stat-card-icon {
  background: rgba(34, 197, 94, 0.14);
  color: #16a34a;
}

.stat-card.model .stat-card-icon {
  background: rgba(139, 92, 246, 0.14);
  color: #7c3aed;
}

.stat-card.source .stat-card-icon {
  background: rgba(100, 116, 139, 0.16);
  color: #64748b;
}

.chart-card {
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

.phase-legend {
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
}

.main-chart {
  width: 100%;
  height: 440px;
}

.chart-empty {
  height: 440px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  color: var(--muted);
}

.summary-card {
  padding: 18px 20px 20px;
}

.summary-body {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.summary-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: rgba(var(--primary-color-rgb), 0.03);
}

.summary-item-label {
  font-size: 12px;
  color: var(--muted);
}

.summary-item-value {
  font-size: 16px;
  font-weight: 700;
  color: var(--text);
  font-variant-numeric: tabular-nums;
  word-break: break-all;
}

.summary-block-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--text);
  margin-bottom: 10px;
}

.summary-muted {
  font-size: 12px;
  color: var(--muted);
}

.summary-error {
  font-size: 12px;
  color: #dc2626;
}

.risk-flag-list {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.risk-flag-tag {
  font-weight: 600;
}

.eval-table-wrap {
  overflow-x: auto;
}

.eval-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;

  th,
  td {
    padding: 8px 10px;
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

.summary-mock {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border: 1px solid rgba(245, 158, 11, 0.35);
  border-radius: 12px;
  background: rgba(245, 158, 11, 0.08);
  font-size: 12px;
  color: var(--text);
}

.summary-empty {
  padding: 24px 0;
  text-align: center;
  font-size: 13px;
  color: var(--muted);
}

@media (max-width: 1200px) {
  .stat-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 768px) {
  .stat-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .main-chart {
    height: 360px;
  }
}
</style>
