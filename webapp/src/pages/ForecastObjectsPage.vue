<template>
  <div class="forecast-objects-page">
    <header class="page-header">
      <div class="page-title">
        <span class="title-chip">预测对象管理</span>
        <p class="title-sub">
          管理参与交易量预测的应用与接口对象，查看准入评估结果、判定原因，并支持人工纳入 / 排除。
        </p>
      </div>
      <div class="header-actions">
        <Button label="准入规则" icon="pi pi-sliders-h" outlined @click="openRulesDialog" />
        <Button label="变化记录" icon="pi pi-history" outlined @click="openHistoryDialog" />
      </div>
    </header>

    <Message v-if="!listError" severity="warn" :closable="false" class="mock-banner">
      <div class="mock-banner-content">
        <Tag value="Mock" severity="warn" class="mock-banner-tag" />
        <span>当前为 Mock 演示数据，不可用于生产报告。</span>
        <span v-if="mockObjectCount > 0" class="mock-banner-meta">
          共 {{ mockObjectCount }} 个对象来自 Mock 数据源
        </span>
      </div>
    </Message>

    <Message v-if="listError" severity="error" :closable="false" class="mock-banner">
      <div class="mock-banner-content">
        <span>{{ listError }}</span>
        <Button label="重试" icon="pi pi-refresh" text size="small" @click="loadList" />
      </div>
    </Message>

    <section class="stat-grid">
      <div class="card stat-card eligible" data-anim>
        <div class="stat-card-head">
          <span class="stat-card-icon"><i class="ri-checkbox-circle-line"></i></span>
          <span class="stat-card-label">纳入预测对象</span>
        </div>
        <div class="stat-card-value">{{ stats.eligibleCount }}</div>
        <div class="stat-card-foot">占全部对象 {{ stats.eligibleRatioText }}</div>
      </div>
      <div class="card stat-card cold" data-anim>
        <div class="stat-card-head">
          <span class="stat-card-icon"><i class="ri-snowflake-line"></i></span>
          <span class="stat-card-label">冷系统</span>
        </div>
        <div class="stat-card-value">{{ stats.coldCount }}</div>
        <div class="stat-card-foot">交易量过低，暂不预测</div>
      </div>
      <div class="card stat-card probation" data-anim>
        <div class="stat-card-head">
          <span class="stat-card-icon"><i class="ri-time-line"></i></span>
          <span class="stat-card-label">观察期</span>
        </div>
        <div class="stat-card-value">{{ stats.probationCount }}</div>
        <div class="stat-card-foot">数据量接近准入线</div>
      </div>
      <div class="card stat-card total" data-anim>
        <div class="stat-card-head">
          <span class="stat-card-icon"><i class="ri-database-2-line"></i></span>
          <span class="stat-card-label">总对象数</span>
        </div>
        <div class="stat-card-value">{{ stats.totalCount }}</div>
        <div class="stat-card-foot">其中人工干预 {{ stats.manualCount }} 个</div>
      </div>
    </section>

    <section class="card filter-card" data-anim>
      <div class="filter-toolbar">
        <div class="filter-field">
          <label class="filter-label" for="forecast-status-filter">状态</label>
          <Dropdown
            v-model="statusFilter"
            inputId="forecast-status-filter"
            class="filter-dropdown"
            :options="statusOptions"
            optionLabel="label"
            optionValue="value"
            placeholder="全部状态"
          />
        </div>
        <div class="filter-field">
          <label class="filter-label" for="forecast-app-filter">应用名称</label>
          <Dropdown
            v-model="appFilter"
            inputId="forecast-app-filter"
            class="filter-dropdown"
            :options="appOptions"
            optionLabel="label"
            optionValue="value"
            :disabled="appOptions.length <= 1"
            placeholder="全部应用"
            showClear
          />
        </div>
        <div class="filter-spacer"></div>
        <div class="filter-actions">
          <Button
            label="重新评估"
            icon="pi pi-refresh"
            severity="secondary"
            :loading="evaluating"
            @click="handleEvaluateAll"
          />
          <Button
            label="刷新"
            icon="pi pi-sync"
            outlined
            :loading="listLoading"
            @click="loadList"
          />
        </div>
      </div>
      <div class="filter-summary">
        当前筛选结果 {{ filteredRows.length }} 条，共 {{ rows.length }} 个评估对象
      </div>
    </section>

    <section class="card table-card" data-anim>
      <div class="card-header">
        <div class="card-title">
          <span class="card-icon blue"><i class="ri-list-check-2"></i></span>
          预测对象列表
        </div>
      </div>
      <DataTable
        :value="filteredRows"
        data-key="rowKey"
        class="p-datatable-sm forecast-table"
        :loading="listLoading"
        :paginator="true"
        :rows="20"
        :rows-per-page-options="[10, 20, 50, 100]"
        paginator-template="CurrentPageReport FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink RowsPerPageDropdown"
        current-page-report-template="第 {first} - {last} 条，共 {totalRecords} 条"
        removable-sort
        sort-mode="single"
      >
        <template #empty>
          <div class="table-empty">暂无预测对象数据</div>
        </template>
        <Column field="app_name" header="应用名称" sortable style="min-width: 130px">
          <template #body="{ data }">
            <span class="cell-strong">{{ data.app_name }}</span>
          </template>
        </Column>
        <Column field="uri_template" header="URI" sortable style="min-width: 220px">
          <template #body="{ data }">
            <span :class="['cell-uri', { 'is-app-level': !data.uri_template }]" :title="data.uri_template">
              {{ data.uriLabel }}
            </span>
          </template>
        </Column>
        <Column field="total_requests" header="交易总量" sortable style="min-width: 110px">
          <template #body="{ data }">
            <span class="cell-number">{{ data.totalRequestsText }}</span>
          </template>
        </Column>
        <Column field="active_days" header="活跃天数" sortable style="min-width: 100px">
          <template #body="{ data }">
            <span class="cell-number">{{ data.activeDaysText }}</span>
          </template>
        </Column>
        <Column field="data_completeness" header="数据完整率" sortable style="min-width: 110px">
          <template #body="{ data }">
            <span class="cell-number">{{ data.completenessText }}</span>
          </template>
        </Column>
        <Column field="weekly_seasonality_score" header="周周期强度" sortable style="min-width: 110px">
          <template #body="{ data }">
            <span class="cell-number">{{ data.weeklySeasonalityText }}</span>
          </template>
        </Column>
        <Column field="eligibility_score" header="资格评分" sortable style="min-width: 100px">
          <template #body="{ data }">
            <span class="cell-number">{{ data.eligibilityScoreText }}</span>
          </template>
        </Column>
        <Column field="predictability" header="可预测性" sortable style="min-width: 100px">
          <template #body="{ data }">
            <Tag :value="predictabilityLabel(data.predictability)" :severity="predictabilitySeverity(data.predictability)" />
          </template>
        </Column>
        <Column field="status" header="状态" sortable style="min-width: 130px">
          <template #body="{ data }">
            <Tag :value="statusLabel(data.status)" :severity="statusSeverity(data.status)" />
          </template>
        </Column>
        <Column field="data_source" header="数据来源" style="min-width: 100px">
          <template #body="{ data }">
            <Tag :value="dataSourceLabel(data.data_source)" :severity="dataSourceSeverity(data.data_source)" />
          </template>
        </Column>
        <Column header="排除原因" style="min-width: 110px">
          <template #body="{ data }">
            <Button
              v-if="data.reasons && data.reasons.length > 0"
              :label="`查看 (${data.reasons.length})`"
              text
              size="small"
              @click="openReasonsDialog(data)"
            />
            <span v-else class="cell-muted">—</span>
          </template>
        </Column>
        <Column header="操作" style="min-width: 180px">
          <template #body="{ data }">
            <div class="row-actions">
              <Button
                label="纳入预测"
                icon="pi pi-check"
                text
                size="small"
                :disabled="data.status === 'manually_included'"
                @click="openOverrideDialog(data, 'include')"
              />
              <Button
                label="排除预测"
                icon="pi pi-times"
                text
                size="small"
                severity="danger"
                :disabled="data.status === 'manually_excluded'"
                @click="openOverrideDialog(data, 'exclude')"
              />
            </div>
          </template>
        </Column>
      </DataTable>
    </section>

    <!-- 排除原因 -->
    <Dialog
      v-model:visible="reasonsVisible"
      modal
      :draggable="false"
      header="评估判定原因"
      class="forecast-dialog"
      :style="{ width: 'min(620px, calc(100vw - 32px))' }"
    >
      <div v-if="reasonsTarget" class="reasons-body">
        <div class="reasons-object">
          <div class="reasons-object-name">{{ reasonsTarget.objectLabel }}</div>
          <Tag :value="statusLabel(reasonsTarget.status)" :severity="statusSeverity(reasonsTarget.status)" />
        </div>
        <ul v-if="reasonsTarget.reasons && reasonsTarget.reasons.length > 0" class="reasons-list">
          <li v-for="(reason, index) in reasonsTarget.reasons" :key="`reason-${index}`">
            <span class="reasons-index">{{ index + 1 }}</span>
            <span class="reasons-text">{{ reason }}</span>
          </li>
        </ul>
        <div v-else class="reasons-empty">该对象暂无判定原因记录。</div>
        <div v-if="reasonsTarget.override_reason" class="reasons-override">
          <div class="reasons-override-title">人工操作记录</div>
          <div class="reasons-override-row">
            <span>操作人</span>
            <span>{{ reasonsTarget.override_by || '—' }}</span>
          </div>
          <div class="reasons-override-row">
            <span>操作时间</span>
            <span>{{ formatDateTime(reasonsTarget.override_at) }}</span>
          </div>
          <div class="reasons-override-row">
            <span>原因</span>
            <span>{{ reasonsTarget.override_reason }}</span>
          </div>
        </div>
      </div>
    </Dialog>

    <!-- 人工纳入 / 排除 -->
    <Dialog
      v-model:visible="overrideVisible"
      modal
      :draggable="false"
      :header="overrideTitle"
      class="forecast-dialog"
      :style="{ width: 'min(560px, calc(100vw - 32px))' }"
    >
      <div class="override-body">
        <div class="form-row">
          <span class="form-label">预测对象</span>
          <span class="form-value">{{ overrideTarget ? overrideTarget.objectLabel : '—' }}</span>
        </div>
        <div class="form-row">
          <span class="form-label">目标状态</span>
          <span class="form-value">
            <Tag :value="statusLabel(overrideNewStatus)" :severity="statusSeverity(overrideNewStatus)" />
          </span>
        </div>
        <div class="form-row">
          <span class="form-label">
            操作原因
            <span class="form-required">*</span>
          </span>
          <Textarea
            v-model="overrideReason"
            class="override-textarea"
            rows="3"
            auto-resize
            placeholder="请填写纳入 / 排除该对象的业务原因（必填，将写入审计记录）"
          />
        </div>
        <div class="form-row">
          <span class="form-label">操作人</span>
          <InputText v-model="overrideOperator" class="override-input" placeholder="操作人" />
        </div>
        <div v-if="overrideError" class="override-error">{{ overrideError }}</div>
      </div>
      <template #footer>
        <Button label="取消" text @click="overrideVisible = false" />
        <Button label="确认提交" :loading="overrideSubmitting" :disabled="overrideSubmitting" @click="submitOverride" />
      </template>
    </Dialog>

    <!-- 准入规则 -->
    <Dialog
      v-model:visible="rulesVisible"
      modal
      :draggable="false"
      header="预测准入规则"
      class="forecast-dialog"
      :style="{ width: 'min(720px, calc(100vw - 32px))' }"
    >
      <div v-if="rulesLoading" class="dialog-loading">规则加载中…</div>
      <div v-else-if="rulesError" class="dialog-error">{{ rulesError }}</div>
      <div v-else-if="rulesData" class="rules-body">
        <div class="rules-section">
          <div class="rules-section-title">阈值配置</div>
          <div class="rules-grid">
            <div v-for="item in ruleThresholdRows" :key="item.key" class="rules-item">
              <span class="rules-item-label">{{ item.label }}</span>
              <span class="rules-item-value">{{ item.value }}</span>
            </div>
          </div>
        </div>
        <div class="rules-section">
          <div class="rules-section-title">资格评分权重</div>
          <div class="rules-grid">
            <div v-for="item in ruleWeightRows" :key="item.key" class="rules-item">
              <span class="rules-item-label">{{ item.label }}</span>
              <span class="rules-item-value">{{ item.value }}</span>
            </div>
          </div>
        </div>
        <div class="rules-section">
          <div class="rules-section-title">可预测性分档</div>
          <div class="rules-band-list">
            <div v-for="band in ruleBandRows" :key="`band-${band.min}`" class="rules-band">
              <span class="rules-band-score">≥ {{ band.min }}</span>
              <Tag :value="band.label" :severity="predictabilitySeverity(band.band)" />
            </div>
          </div>
        </div>
      </div>
    </Dialog>

    <!-- 资格变化记录 -->
    <Dialog
      v-model:visible="historyVisible"
      modal
      :draggable="false"
      header="资格变化记录"
      class="forecast-dialog"
      :style="{ width: 'min(980px, calc(100vw - 32px))' }"
    >
      <div v-if="historyLoading" class="dialog-loading">记录加载中…</div>
      <div v-else-if="historyError" class="dialog-error">{{ historyError }}</div>
      <DataTable
        v-else
        :value="historyRows"
        data-key="historyKey"
        class="p-datatable-sm forecast-table"
        :paginator="historyRows.length > 10"
        :rows="10"
        :rows-per-page-options="[10, 20, 50]"
        paginator-template="CurrentPageReport FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink"
        current-page-report-template="第 {first} - {last} 条，共 {totalRecords} 条"
      >
        <template #empty>
          <div class="table-empty">暂无资格变化记录</div>
        </template>
        <Column header="对象" style="min-width: 200px">
          <template #body="{ data }">
            <span class="cell-strong">{{ data.objectLabel }}</span>
          </template>
        </Column>
        <Column header="原状态" style="min-width: 130px">
          <template #body="{ data }">
            <Tag v-if="data.old_status" :value="statusLabel(data.old_status)" :severity="statusSeverity(data.old_status)" />
            <span v-else class="cell-muted">—</span>
          </template>
        </Column>
        <Column header="新状态" style="min-width: 130px">
          <template #body="{ data }">
            <Tag v-if="data.new_status" :value="statusLabel(data.new_status)" :severity="statusSeverity(data.new_status)" />
            <span v-else class="cell-muted">—</span>
          </template>
        </Column>
        <Column header="操作人" style="min-width: 100px">
          <template #body="{ data }">
            <span>{{ data.operator || '—' }}</span>
          </template>
        </Column>
        <Column header="原因" style="min-width: 220px">
          <template #body="{ data }">
            <span :title="data.reason || ''">{{ data.reason || '—' }}</span>
          </template>
        </Column>
        <Column header="时间" style="min-width: 160px">
          <template #body="{ data }">
            <span class="cell-muted">{{ formatDateTime(data.occurred_at) }}</span>
          </template>
        </Column>
      </DataTable>
    </Dialog>
  </div>
</template>

<script setup lang="ts">
/**
 * 预测对象管理页（阶段二交付物）。
 * 页面文案全部为中文硬编码，按需求不接入 vue-i18n。
 */
import { computed, onMounted, ref } from 'vue';
import Button from 'primevue/button';
import Column from 'primevue/column';
import DataTable from 'primevue/datatable';
import Dialog from 'primevue/dialog';
import Dropdown from 'primevue/dropdown';
import InputText from 'primevue/inputtext';
import Message from 'primevue/message';
import Tag from 'primevue/tag';
import Textarea from 'primevue/textarea';
import { useToast } from 'primevue/usetoast';
import {
  evaluateAllEligibility,
  fetchEligibilityHistory,
  fetchEligibilityList,
  fetchEligibilityRules,
  overrideEligibility,
} from '@/api/forecast';
import type {
  EligibilityHistoryRecord,
  EligibilityRules,
  EligibilityStatus,
  ForecastEligibilityObject,
} from '@/api/forecast';
import { formatBeijingDateTimeWithSeconds } from '@/utils';

/** 表格行视图模型：原始字段 + 展示用格式化文本 */
interface ForecastRow extends ForecastEligibilityObject {
  rowKey: string;
  objectLabel: string;
  uriLabel: string;
  totalRequestsText: string;
  activeDaysText: string;
  completenessText: string;
  weeklySeasonalityText: string;
  eligibilityScoreText: string;
}

/** 状态中文标签映射 */
const STATUS_LABELS: Record<string, string> = {
  eligible: '符合预测条件',
  probation: '观察期',
  cold: '冷系统',
  insufficient_history: '历史数据不足',
  poor_data_quality: '数据质量不合格',
  low_predictability: '缺乏有效规律',
  manually_included: '人工纳入',
  manually_excluded: '人工排除',
};

/** 状态对应的 PrimeVue Tag 语义色 */
const STATUS_SEVERITIES: Record<string, string> = {
  eligible: 'success',
  cold: 'secondary',
  probation: 'warn',
  manually_included: 'info',
};

/** 可预测性中文标签映射 */
const PREDICTABILITY_LABELS: Record<string, string> = {
  high: '高',
  medium: '一般',
  low: '低',
  none: '不具备',
};

/** 可预测性对应的 PrimeVue Tag 语义色 */
const PREDICTABILITY_SEVERITIES: Record<string, string> = {
  high: 'success',
  medium: 'warn',
  low: 'danger',
  none: 'secondary',
};

/** 准入规则字段中文标签 */
const RULE_LABELS: Record<string, string> = {
  lookback_days: '观察窗口（天）',
  min_history_days_full: '历史充分天数下限',
  min_history_days_min: '历史不足天数下限',
  min_completeness: '数据完整率下限',
  min_total_requests_eligible: '进入评估的请求量下限',
  min_active_days_eligible: '进入评估的活跃天数下限',
  cold_total_requests: '冷系统请求量上限',
  cold_active_days: '冷系统活跃天数上限',
  probation_total_requests: '观察期请求量上限',
  probation_active_days: '观察期活跃天数上限',
  seasonality_acf_threshold: '周期性自相关阈值',
  batch_concentration_threshold: '批处理夜间集中度阈值',
};

/** 需要按百分比展示的规则字段 */
const RULE_PERCENT_KEYS = ['min_completeness', 'seasonality_acf_threshold', 'batch_concentration_threshold'];

/** 评分权重中文标签 */
const SCORE_WEIGHT_LABELS: Record<string, string> = {
  completeness: '数据完整性',
  history_coverage: '历史覆盖时间',
  volume: '交易量充足程度',
  active_days: '活跃天数',
  seasonality: '时间周期规律',
  stability: '交易量稳定性',
};

/** 全量拉取上限（后端允许 1~1000） */
const LIST_LIMIT = 1000;

/** 默认操作人 */
const DEFAULT_OPERATOR = 'admin';

const toast = useToast();

const rows = ref<ForecastRow[]>([]);
const listLoading = ref(false);
const listError = ref('');
const evaluating = ref(false);
const statusFilter = ref<string>('');
const appFilter = ref<string>('');

const reasonsVisible = ref(false);
const reasonsTarget = ref<ForecastRow | null>(null);

const overrideVisible = ref(false);
const overrideMode = ref<'include' | 'exclude'>('include');
const overrideTarget = ref<ForecastRow | null>(null);
const overrideReason = ref('');
const overrideOperator = ref(DEFAULT_OPERATOR);
const overrideSubmitting = ref(false);
const overrideError = ref('');

const rulesVisible = ref(false);
const rulesLoading = ref(false);
const rulesError = ref('');
const rulesData = ref<EligibilityRules | null>(null);

const historyVisible = ref(false);
const historyLoading = ref(false);
const historyError = ref('');
const historyRawRows = ref<EligibilityHistoryRecord[]>([]);

/** 状态筛选项（中文标签） */
const statusOptions = [
  { label: '全部状态', value: '' },
  { label: '符合预测条件', value: 'eligible' },
  { label: '观察期', value: 'probation' },
  { label: '冷系统', value: 'cold' },
  { label: '历史数据不足', value: 'insufficient_history' },
  { label: '数据质量不合格', value: 'poor_data_quality' },
  { label: '缺乏有效规律', value: 'low_predictability' },
  { label: '人工纳入', value: 'manually_included' },
  { label: '人工排除', value: 'manually_excluded' },
];

/** 应用名筛选项：从列表数据中提取去重 */
const appOptions = computed(() => {
  const names = Array.from(new Set(rows.value.map((row) => row.app_name).filter((name) => Boolean(name))));
  names.sort((a, b) => a.localeCompare(b, 'zh-CN'));
  return [{ label: '全部应用', value: '' }, ...names.map((name) => ({ label: name, value: name }))];
});

/** 本地筛选后的表格行 */
const filteredRows = computed(() =>
  rows.value.filter((row) => {
    if (statusFilter.value && row.status !== statusFilter.value) {
      return false;
    }
    if (appFilter.value && row.app_name !== appFilter.value) {
      return false;
    }
    return true;
  })
);

/** 顶部统计卡片数据（基于全量列表本地统计） */
const stats = computed(() => {
  const total = rows.value.length;
  const eligibleCount = rows.value.filter((row) => row.status === 'eligible').length;
  const coldCount = rows.value.filter((row) => row.status === 'cold').length;
  const probationCount = rows.value.filter((row) => row.status === 'probation').length;
  const manualCount = rows.value.filter(
    (row) => row.status === 'manually_included' || row.status === 'manually_excluded'
  ).length;
  return {
    totalCount: total,
    eligibleCount,
    coldCount,
    probationCount,
    manualCount,
    eligibleRatioText: total > 0 ? `${((eligibleCount / total) * 100).toFixed(1)}%` : '0%',
  };
});

/** Mock 数据源对象数量 */
const mockObjectCount = computed(
  () => rows.value.filter((row) => String(row.data_source || '').toLowerCase() === 'mock').length
);

/** 规则阈值展示行 */
const ruleThresholdRows = computed(() => {
  const rules = rulesData.value;
  if (!rules) {
    return [] as Array<{ key: string; label: string; value: string }>;
  }
  return Object.keys(RULE_LABELS)
    .filter((key) => rules[key] !== undefined && rules[key] !== null)
    .map((key) => ({
      key,
      label: RULE_LABELS[key],
      value: formatRuleValue(key, rules[key]),
    }));
});

/** 规则评分权重展示行 */
const ruleWeightRows = computed(() => {
  const weights = rulesData.value?.score_weights || {};
  return Object.keys(weights).map((key) => ({
    key,
    label: SCORE_WEIGHT_LABELS[key] || key,
    value: `${(Number(weights[key]) * 100).toFixed(0)}%`,
  }));
});

/** 规则可预测性分档展示行 */
const ruleBandRows = computed(() => {
  const bands = rulesData.value?.predictability_bands || [];
  return bands.map((band) => ({
    min: band.min,
    label: PREDICTABILITY_LABELS[band.label] || band.label,
    band: band.label,
  }));
});

/** 资格变化记录展示行 */
const historyRows = computed(() =>
  historyRawRows.value.map((record, index) => ({
    ...record,
    historyKey: `${record.app_name}-${record.uri_template}-${record.occurred_at}-${index}`,
    objectLabel: buildObjectLabel(record.app_name, record.uri_template),
  }))
);

const overrideTitle = computed(() =>
  overrideMode.value === 'include' ? '人工纳入预测' : '人工排除预测'
);

const overrideNewStatus = computed<EligibilityStatus>(
  () => (overrideMode.value === 'include' ? 'manually_included' : 'manually_excluded')
);

/**
 * 状态中文标签。
 * @param status 状态值
 */
function statusLabel(status: string): string {
  return STATUS_LABELS[status] || status || '未知';
}

/**
 * 状态标签语义色：eligible 绿 / cold 灰 / probation 黄 / 人工纳入 蓝 / 其余红。
 * @param status 状态值
 */
function statusSeverity(status: string): string {
  return STATUS_SEVERITIES[status] || 'danger';
}

/**
 * 可预测性中文标签。
 * @param band 可预测性档位
 */
function predictabilityLabel(band: string): string {
  return PREDICTABILITY_LABELS[band] || band || '—';
}

/**
 * 可预测性标签语义色。
 * @param band 可预测性档位
 */
function predictabilitySeverity(band: string): string {
  return PREDICTABILITY_SEVERITIES[band] || 'secondary';
}

/**
 * 数据来源中文标签。
 * @param source data_source 字段值
 */
function dataSourceLabel(source: string): string {
  return String(source || '').toLowerCase() === 'mock' ? 'Mock' : source || '—';
}

/**
 * 数据来源标签语义色。
 * @param source data_source 字段值
 */
function dataSourceSeverity(source: string): string {
  return String(source || '').toLowerCase() === 'mock' ? 'warn' : 'info';
}

/**
 * 数字千分位格式化。
 * @param value 数值
 */
function formatNumber(value: number): string {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return '—';
  }
  return numeric.toLocaleString('zh-CN');
}

/**
 * 比率格式化为百分比。
 * @param value 0-1 之间的比率
 * @param digits 小数位数
 */
function formatPercent(value: number, digits = 1): string {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return '—';
  }
  return `${(numeric * 100).toFixed(digits)}%`;
}

/**
 * 时间格式化：统一按东八区（北京时间）展示，避免受浏览器 / 容器时区影响。
 * @param value ISO 时间字符串
 */
function formatDateTime(value: string | null | undefined): string {
  return formatBeijingDateTimeWithSeconds(value);
}

/**
 * 规则数值格式化：比率字段按百分比展示，其余按原值展示。
 * @param key 规则字段名
 * @param value 规则值
 */
function formatRuleValue(key: string, value: unknown): string {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return String(value ?? '—');
  }
  if (RULE_PERCENT_KEYS.includes(key)) {
    return formatPercent(numeric, 0);
  }
  return formatNumber(numeric);
}

/**
 * 构造对象展示名：应用名 + URI（应用级对象标注为汇总）。
 * @param appName 应用名
 * @param uriTemplate URI 模板
 */
function buildObjectLabel(appName: string, uriTemplate: string): string {
  const uri = uriTemplate || '';
  if (!uri) {
    return `${appName}（应用级汇总）`;
  }
  return `${appName} ${uri}`;
}

/**
 * 把后端原始对象转换为表格行视图模型。
 * @param raw 后端返回的预测对象
 * @param index 行序号（用于生成稳定 key）
 */
function buildRow(raw: ForecastEligibilityObject, index: number): ForecastRow {
  const uriTemplate = raw.uri_template || '';
  const level = raw.level || (uriTemplate ? 'uri' : 'app');
  const safeReasons = Array.isArray(raw.reasons) ? raw.reasons : [];
  return {
    ...raw,
    level: level as ForecastEligibilityObject['level'],
    uri_template: uriTemplate,
    reasons: safeReasons,
    rowKey: `${level}::${raw.app_name || ''}::${uriTemplate}::${index}`,
    objectLabel: buildObjectLabel(raw.app_name || '', uriTemplate),
    uriLabel: uriTemplate || '（应用级汇总）',
    totalRequestsText: formatNumber(raw.total_requests),
    activeDaysText: `${formatNumber(raw.active_days)} 天`,
    completenessText: formatPercent(raw.data_completeness, 1),
    weeklySeasonalityText: Number(raw.weekly_seasonality_score ?? 0).toFixed(2),
    eligibilityScoreText: Number(raw.eligibility_score ?? 0).toFixed(1),
  };
}

/**
 * 加载预测对象列表（全量拉取，本地统计与筛选）。
 */
async function loadList() {
  listLoading.value = true;
  listError.value = '';
  try {
    const data = await fetchEligibilityList({ limit: LIST_LIMIT, offset: 0 });
    rows.value = data.map((item, index) => buildRow(item, index));
    // 应用名下架后清空无效的筛选值，避免列表空白
    if (appFilter.value && !rows.value.some((row) => row.app_name === appFilter.value)) {
      appFilter.value = '';
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : '获取预测对象列表失败';
    rows.value = [];
    listError.value = `${message}（请确认预测服务已启动：http://localhost:8090）`;
  } finally {
    listLoading.value = false;
  }
}

/**
 * 触发全量重新评估并刷新列表。
 */
async function handleEvaluateAll() {
  evaluating.value = true;
  try {
    const result = await evaluateAllEligibility();
    toast.add({
      severity: 'success',
      summary: '评估完成',
      detail: `已完成 ${result.evaluated} 个对象的资格评估`,
      life: 3000,
    });
    await loadList();
  } catch (error) {
    const message = error instanceof Error ? error.message : '全量评估失败';
    toast.add({ severity: 'error', summary: '评估失败', detail: message, life: 5000 });
  } finally {
    evaluating.value = false;
  }
}

/**
 * 打开判定原因弹窗。
 * @param row 表格行
 */
function openReasonsDialog(row: ForecastRow) {
  reasonsTarget.value = row;
  reasonsVisible.value = true;
}

/**
 * 打开人工纳入 / 排除弹窗。
 * @param row 表格行
 * @param mode include=纳入，exclude=排除
 */
function openOverrideDialog(row: ForecastRow, mode: 'include' | 'exclude') {
  overrideTarget.value = row;
  overrideMode.value = mode;
  overrideReason.value = '';
  overrideOperator.value = DEFAULT_OPERATOR;
  overrideError.value = '';
  overrideVisible.value = true;
}

/**
 * 提交人工覆盖操作。
 */
async function submitOverride() {
  const target = overrideTarget.value;
  if (!target) {
    return;
  }
  const reason = overrideReason.value.trim();
  if (!reason) {
    overrideError.value = '请填写操作原因';
    return;
  }
  const operator = overrideOperator.value.trim() || DEFAULT_OPERATOR;
  overrideError.value = '';
  overrideSubmitting.value = true;
  try {
    await overrideEligibility({
      level: target.level,
      app_name: target.app_name,
      uri_template: target.uri_template || '',
      new_status: overrideNewStatus.value,
      reason,
      operator,
    });
    overrideVisible.value = false;
    toast.add({
      severity: 'success',
      summary: overrideMode.value === 'include' ? '已纳入预测' : '已排除预测',
      detail: `${target.objectLabel} 状态已更新为「${statusLabel(overrideNewStatus.value)}」`,
      life: 3000,
    });
    await loadList();
  } catch (error) {
    const message = error instanceof Error ? error.message : '提交人工操作失败';
    overrideError.value = message;
    toast.add({ severity: 'error', summary: '操作失败', detail: message, life: 5000 });
  } finally {
    overrideSubmitting.value = false;
  }
}

/**
 * 打开准入规则弹窗并加载规则配置。
 */
async function openRulesDialog() {
  rulesVisible.value = true;
  rulesLoading.value = true;
  rulesError.value = '';
  try {
    rulesData.value = await fetchEligibilityRules();
  } catch (error) {
    const message = error instanceof Error ? error.message : '获取准入规则失败';
    rulesData.value = null;
    rulesError.value = message;
  } finally {
    rulesLoading.value = false;
  }
}

/**
 * 打开资格变化记录弹窗并加载审计数据。
 */
async function openHistoryDialog() {
  historyVisible.value = true;
  historyLoading.value = true;
  historyError.value = '';
  try {
    historyRawRows.value = await fetchEligibilityHistory(undefined, 200);
  } catch (error) {
    const message = error instanceof Error ? error.message : '获取资格变化记录失败';
    historyRawRows.value = [];
    historyError.value = message;
  } finally {
    historyLoading.value = false;
  }
}

onMounted(() => {
  void loadList();
});
</script>

<style scoped lang="scss">
.forecast-objects-page {
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
  max-width: 640px;
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

.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
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
  font-size: 28px;
  font-weight: 750;
  line-height: 1.1;
  color: var(--text);
}

.stat-card-foot {
  margin-top: 6px;
  font-size: 12px;
  color: var(--muted);
}

.stat-card.eligible .stat-card-icon {
  background: rgba(34, 197, 94, 0.14);
  color: #16a34a;
}

.stat-card.cold .stat-card-icon {
  background: rgba(100, 116, 139, 0.16);
  color: #64748b;
}

.stat-card.probation .stat-card-icon {
  background: rgba(245, 158, 11, 0.16);
  color: #d97706;
}

.stat-card.total .stat-card-icon {
  background: rgba(29, 107, 255, 0.12);
  color: var(--primary);
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

.table-card {
  padding: 18px 20px 20px;
}

.cell-strong {
  font-weight: 600;
  color: var(--text);
}

.cell-number {
  font-variant-numeric: tabular-nums;
  color: var(--text);
}

.cell-muted {
  color: var(--muted);
}

.table-empty {
  padding: 28px 0;
  text-align: center;
  font-size: 13px;
  color: var(--muted);
}

.cell-uri {
  display: inline-block;
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}

.cell-uri.is-app-level {
  color: var(--muted);
  font-style: normal;
}

.row-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

.reasons-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.reasons-object {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border);
}

.reasons-object-name {
  font-size: 14px;
  font-weight: 700;
  color: var(--text);
  word-break: break-all;
}

.reasons-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.reasons-list li {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text);
}

.reasons-index {
  flex: 0 0 20px;
  height: 20px;
  border-radius: 6px;
  background: rgba(var(--primary-color-rgb), 0.12);
  color: var(--primary);
  font-size: 11px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.reasons-text {
  flex: 1;
  word-break: break-word;
}

.reasons-empty,
.dialog-loading,
.dialog-error {
  font-size: 13px;
  color: var(--muted);
  text-align: center;
  padding: 16px 0;
}

.dialog-error {
  color: var(--error-color);
}

.reasons-override {
  border-top: 1px dashed var(--border);
  padding-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.reasons-override-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--muted);
  letter-spacing: 0.04em;
}

.reasons-override-row {
  display: flex;
  gap: 12px;
  font-size: 13px;
}

.reasons-override-row span:first-child {
  flex: 0 0 72px;
  color: var(--muted);
}

.override-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.form-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--muted);
}

.form-required {
  color: var(--error-color);
  margin-left: 2px;
}

.form-value {
  font-size: 13px;
  color: var(--text);
  word-break: break-all;
}

.override-textarea,
.override-input {
  width: 100%;
}

.override-error {
  font-size: 12px;
  color: var(--error-color);
}

.rules-body {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.rules-section-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--text);
  margin-bottom: 10px;
}

.rules-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 18px;
}

.rules-item {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 12px;
  border-radius: var(--radius-xs);
  background: var(--panel-muted);
  font-size: 13px;
}

.rules-item-label {
  color: var(--muted);
}

.rules-item-value {
  font-weight: 700;
  color: var(--text);
  font-variant-numeric: tabular-nums;
}

.rules-band-list {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.rules-band {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: var(--radius-xs);
  background: var(--panel-muted);
  font-size: 13px;
}

.rules-band-score {
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

:deep(.forecast-table .p-datatable-thead > tr > th) {
  background: var(--panel-muted);
  font-size: 12px;
  white-space: nowrap;
}

:deep(.forecast-table .p-datatable-tbody > tr > td) {
  font-size: 13px;
  padding: 8px 12px;
}

:deep(.forecast-table .p-paginator) {
  font-size: 12px;
}

@media (max-width: 1180px) {
  .stat-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .page-header {
    flex-direction: column;
    align-items: stretch;
  }

  .stat-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .rules-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .filter-field,
  .filter-dropdown {
    width: 100%;
    min-width: 0;
  }
}
</style>
