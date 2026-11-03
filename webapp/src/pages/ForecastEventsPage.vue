<template>
  <div class="forecast-events-page">
    <header class="page-header">
      <div class="page-title">
        <span class="title-chip">活动日历</span>
        <p class="title-sub">
          维护影响交易量的业务活动（营销、批处理、促销、上线、节假日），支持预热期 / 正式期 / 回落期日历染色与阶段查询。
        </p>
      </div>
      <div class="header-actions">
        <Button label="初始化 Mock 数据" icon="pi pi-database" outlined :loading="initLoading" @click="handleInitMock" />
        <Button label="新建活动" icon="pi pi-plus" @click="openCreateDialog" />
      </div>
    </header>

    <Message v-if="!listError" severity="warn" :closable="false" class="mock-banner">
      <div class="mock-banner-content">
        <Tag value="Mock" severity="warn" class="mock-banner-tag" />
        <span>当前为 Mock 演示数据，不可用于生产报告。</span>
        <span v-if="mockEventCount > 0" class="mock-banner-meta">共 {{ mockEventCount }} 个活动来自 Mock 数据源</span>
      </div>
    </Message>

    <Message v-if="listError" severity="error" :closable="false" class="mock-banner">
      <div class="mock-banner-content">
        <span>{{ listError }}</span>
        <Button label="重试" icon="pi pi-refresh" text size="small" @click="loadEvents" />
      </div>
    </Message>

    <section class="stat-grid">
      <div class="card stat-card total" data-anim>
        <div class="stat-card-head">
          <span class="stat-card-icon"><i class="ri-calendar-event-line"></i></span>
          <span class="stat-card-label">活动总数</span>
        </div>
        <div class="stat-card-value">{{ stats.totalCount }}</div>
        <div class="stat-card-foot">其中已确认 {{ stats.confirmedCount }} 个</div>
      </div>
      <div class="card stat-card running" data-anim>
        <div class="stat-card-head">
          <span class="stat-card-icon"><i class="ri-play-circle-line"></i></span>
          <span class="stat-card-label">进行中活动</span>
        </div>
        <div class="stat-card-value">{{ stats.runningCount }}</div>
        <div class="stat-card-foot">当前时刻处于正式期</div>
      </div>
      <div class="card stat-card high" data-anim>
        <div class="stat-card-head">
          <span class="stat-card-icon"><i class="ri-alarm-warning-line"></i></span>
          <span class="stat-card-label">高影响活动</span>
        </div>
        <div class="stat-card-value">{{ stats.highImpactCount }}</div>
        <div class="stat-card-foot">预测时须优先纳入事件因子</div>
      </div>
      <div class="card stat-card low" data-anim>
        <div class="stat-card-head">
          <span class="stat-card-icon"><i class="ri-question-line"></i></span>
          <span class="stat-card-label">增幅未标注</span>
        </div>
        <div class="stat-card-value">{{ stats.unknownUpliftCount }}</div>
        <div class="stat-card-foot">数据不足，不做数值编造</div>
      </div>
    </section>

    <section class="card calendar-card" data-anim>
      <div class="card-header">
        <div class="card-title">
          <span class="card-icon orange"><i class="ri-calendar-2-line"></i></span>
          活动日历
        </div>
        <div class="calendar-nav">
          <Button icon="pi pi-chevron-left" text rounded aria-label="上一月" @click="shiftMonth(-1)" />
          <span class="calendar-month">{{ calendarMonthText }}</span>
          <Button icon="pi pi-chevron-right" text rounded aria-label="下一月" @click="shiftMonth(1)" />
          <Button label="今天" text size="small" @click="goCurrentMonth" />
        </div>
      </div>

      <div class="calendar-legend">
        <span class="legend-item"><i class="legend-dot preheat"></i>预热期</span>
        <span class="legend-item"><i class="legend-dot active"></i>正式期</span>
        <span class="legend-item"><i class="legend-dot cooldown"></i>回落期</span>
        <span class="legend-muted">按活动的预热 / 正式 / 回落时间区间染色，点击日期查看当日活动</span>
      </div>

      <div class="calendar-grid">
        <div v-for="weekday in WEEKDAY_LABELS" :key="weekday" class="calendar-weekday">{{ weekday }}</div>
        <div
          v-for="cell in calendarCells"
          :key="cell.key"
          class="calendar-cell"
          :class="{ 'is-outside': !cell.inMonth, 'is-today': cell.isToday, 'is-selected': cell.key === selectedDayKey }"
          @click="selectDay(cell)"
        >
          <span class="calendar-day">{{ cell.day }}</span>
          <div v-if="cell.marks.length > 0" class="calendar-marks">
            <span
              v-for="mark in cell.marks.slice(0, 3)"
              :key="mark.key"
              class="calendar-mark"
              :class="mark.phase"
              :title="`${phaseLabel(mark.phase)}：${mark.event.event_name}`"
            ></span>
            <span v-if="cell.marks.length > 3" class="calendar-mark-more">+{{ cell.marks.length - 3 }}</span>
          </div>
        </div>
      </div>

      <div class="calendar-day-panel">
        <div class="calendar-day-title">{{ selectedDayText }}</div>
        <div v-if="selectedDayEvents.length === 0" class="calendar-day-empty">当日无活动安排</div>
        <div v-else class="calendar-day-list">
          <div v-for="item in selectedDayEvents" :key="item.event.event_id" class="calendar-day-item">
            <Tag :value="phaseLabel(item.phase)" :severity="phaseSeverity(item.phase)" />
            <span class="calendar-day-name">{{ item.event.event_name }}</span>
            <span class="calendar-day-range">{{ formatDateTime(item.event.start_time) }} ~ {{ formatDateTime(item.event.end_time) }}</span>
            <Tag :value="impactLabel(item.event.impact_level)" :severity="impactSeverity(item.event.impact_level)" />
          </div>
        </div>
      </div>
    </section>

    <section class="card filter-card" data-anim>
      <div class="filter-toolbar">
        <div class="filter-field">
          <label class="filter-label" for="events-status-filter">活动状态</label>
          <Dropdown
            v-model="statusFilter"
            inputId="events-status-filter"
            class="filter-dropdown"
            :options="statusOptions"
            optionLabel="label"
            optionValue="value"
            placeholder="全部状态"
          />
        </div>
        <div class="filter-field">
          <label class="filter-label" for="events-type-filter">活动类型</label>
          <Dropdown
            v-model="typeFilter"
            inputId="events-type-filter"
            class="filter-dropdown"
            :options="typeOptions"
            optionLabel="label"
            optionValue="value"
            placeholder="全部类型"
          />
        </div>
        <div class="filter-field">
          <label class="filter-label" for="events-app-filter">受影响应用</label>
          <Dropdown
            v-model="appFilter"
            inputId="events-app-filter"
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
          <Button label="刷新" icon="pi pi-sync" outlined :loading="listLoading" @click="loadEvents" />
        </div>
      </div>
      <div class="filter-summary">当前筛选结果 {{ filteredEvents.length }} 条，共 {{ events.length }} 个活动</div>
    </section>

    <section class="card table-card" data-anim>
      <div class="card-header">
        <div class="card-title">
          <span class="card-icon blue"><i class="ri-list-check-2"></i></span>
          活动列表
        </div>
      </div>
      <DataTable
        :value="filteredEvents"
        data-key="event_id"
        class="p-datatable-sm events-table"
        :loading="listLoading"
        :paginator="true"
        :rows="10"
        :rows-per-page-options="[10, 20, 50]"
        paginator-template="CurrentPageReport FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink RowsPerPageDropdown"
        current-page-report-template="第 {first} - {last} 条，共 {totalRecords} 条"
        removable-sort
        sort-mode="single"
      >
        <template #empty>
          <div class="table-empty">暂无活动数据，可点击「初始化 Mock 数据」生成演示活动</div>
        </template>
        <Column field="event_name" header="活动名称" sortable style="min-width: 180px">
          <template #body="{ data }">
            <div class="event-name-cell">
              <span class="cell-strong">{{ data.event_name }}</span>
              <span class="event-sub">{{ data.business_type || '—' }}</span>
            </div>
          </template>
        </Column>
        <Column field="event_type" header="类型" sortable style="min-width: 100px">
          <template #body="{ data }">
            <Tag :value="typeLabel(data.event_type)" severity="info" />
          </template>
        </Column>
        <Column field="start_time" header="活动时间" sortable style="min-width: 200px">
          <template #body="{ data }">
            <span class="cell-number">{{ formatDateTime(data.start_time) }} ~ {{ formatDateTime(data.end_time) }}</span>
          </template>
        </Column>
        <Column header="预热 / 回落" style="min-width: 180px">
          <template #body="{ data }">
            <div class="event-phase-cell">
              <span>预热：{{ formatDateTime(data.preheat_start) }} ~ {{ formatDateTime(data.preheat_end) }}</span>
              <span>回落至：{{ formatDateTime(data.cooldown_end) }}</span>
            </div>
          </template>
        </Column>
        <Column header="受影响应用" style="min-width: 160px">
          <template #body="{ data }">
            <div class="chip-list">
              <Tag v-for="app in data.target_apps || []" :key="app" :value="app" severity="secondary" />
              <span v-if="!(data.target_apps || []).length" class="cell-muted">—</span>
            </div>
          </template>
        </Column>
        <Column header="影响范围" style="min-width: 180px">
          <template #body="{ data }">
            <span v-if="(data.target_uris || []).length > 0" :title="(data.target_uris || []).join('、')" class="cell-uri">
              {{ (data.target_uris || []).join('、') }}
            </span>
            <Tag v-else value="全部 URL" severity="secondary" />
          </template>
        </Column>
        <Column field="expected_uplift" header="预期增幅" sortable style="min-width: 130px">
          <template #body="{ data }">
            <span v-if="data.expected_uplift === null || data.expected_uplift === undefined" class="uplift-unknown">
              <Tag value="数据不足" severity="warn" />
              <span class="uplift-hint">低置信度</span>
            </span>
            <span v-else class="cell-number">+{{ Number(data.expected_uplift).toFixed(1) }}%</span>
          </template>
        </Column>
        <Column field="impact_level" header="影响等级" sortable style="min-width: 100px">
          <template #body="{ data }">
            <Tag :value="impactLabel(data.impact_level)" :severity="impactSeverity(data.impact_level)" />
          </template>
        </Column>
        <Column field="confidence" header="置信度" sortable style="min-width: 90px">
          <template #body="{ data }">
            <Tag :value="confidenceLabel(data.confidence)" :severity="confidenceSeverity(data.confidence)" />
          </template>
        </Column>
        <Column field="status" header="状态" sortable style="min-width: 100px">
          <template #body="{ data }">
            <Tag :value="statusLabel(data.status)" :severity="statusSeverity(data.status)" />
          </template>
        </Column>
        <Column header="操作" style="min-width: 170px">
          <template #body="{ data }">
            <div class="row-actions">
              <Button label="阶段查询" text size="small" @click="openPhaseDialog(data)" />
              <Button label="删除" text size="small" severity="danger" @click="openDeleteDialog(data)" />
            </div>
          </template>
        </Column>
      </DataTable>
    </section>

    <!-- 新建活动 -->
    <Dialog
      v-model:visible="createVisible"
      modal
      :draggable="false"
      header="新建活动"
      class="events-dialog"
      :style="{ width: 'min(760px, calc(100vw - 32px))' }"
    >
      <div v-if="createErrors.length > 0" class="form-error-box">
        <div class="form-error-title">{{ createErrorMessage }}</div>
        <ul class="form-error-list">
          <li v-for="(item, index) in createErrors" :key="`err-${index}`">{{ item }}</li>
        </ul>
      </div>
      <div class="form-grid">
        <div class="form-row span-2">
          <span class="form-label">活动名称 <span class="form-required">*</span></span>
          <InputText v-model="form.event_name" class="form-control" placeholder="例如：2026 双十一营销活动" />
        </div>
        <div class="form-row">
          <span class="form-label">活动类型 <span class="form-required">*</span></span>
          <Dropdown v-model="form.event_type" :options="typeOptions.filter((item) => item.value)" optionLabel="label" optionValue="value" class="form-control" />
        </div>
        <div class="form-row">
          <span class="form-label">活动状态</span>
          <Dropdown v-model="form.status" :options="statusOptions.filter((item) => item.value)" optionLabel="label" optionValue="value" class="form-control" />
        </div>
        <div class="form-row">
          <span class="form-label">开始时间 <span class="form-required">*</span></span>
          <input v-model="form.start_time" type="datetime-local" class="native-input" />
        </div>
        <div class="form-row">
          <span class="form-label">结束时间 <span class="form-required">*</span></span>
          <input v-model="form.end_time" type="datetime-local" class="native-input" />
        </div>
        <div class="form-row">
          <span class="form-label">预热开始</span>
          <input v-model="form.preheat_start" type="datetime-local" class="native-input" />
        </div>
        <div class="form-row">
          <span class="form-label">预热结束</span>
          <input v-model="form.preheat_end" type="datetime-local" class="native-input" />
        </div>
        <div class="form-row">
          <span class="form-label">回落结束</span>
          <input v-model="form.cooldown_end" type="datetime-local" class="native-input" />
        </div>
        <div class="form-row">
          <span class="form-label">影响等级</span>
          <Dropdown v-model="form.impact_level" :options="impactOptions" optionLabel="label" optionValue="value" class="form-control" />
        </div>
        <div class="form-row span-2">
          <span class="form-label">受影响应用 <span class="form-required">*</span></span>
          <Textarea v-model="form.target_apps_text" rows="2" auto-resize class="form-control" placeholder="多个应用用逗号或换行分隔，例如：core-payment, core-card" />
        </div>
        <div class="form-row span-2">
          <span class="form-label">受影响 URI</span>
          <Textarea v-model="form.target_uris_text" rows="2" auto-resize class="form-control" placeholder="留空表示该应用下全部 URL；多个用逗号或换行分隔" />
        </div>
        <div class="form-row">
          <span class="form-label">预期增幅（%）</span>
          <InputNumber v-model="form.expected_uplift" class="form-control" :min-fraction-digits="0" :max-fraction-digits="2" placeholder="留空表示未标注" />
        </div>
        <div class="form-row">
          <span class="form-label">业务类型</span>
          <InputText v-model="form.business_type" class="form-control" placeholder="例如：支付营销" />
        </div>
        <div class="form-row">
          <span class="form-label">活动负责人</span>
          <InputText v-model="form.event_owner" class="form-control" placeholder="例如：零售支付运营组" />
        </div>
        <div class="form-row">
          <span class="form-label">历史事件 ID</span>
          <InputText v-model="form.historical_event_id" class="form-control" placeholder="可选，用于同比参考" />
        </div>
        <div class="form-row">
          <span class="form-label">活动 ID</span>
          <InputText v-model="form.event_id" class="form-control" placeholder="留空由系统生成" />
        </div>
        <div class="form-row">
          <span class="form-label">数据来源</span>
          <InputText v-model="form.data_source" class="form-control" placeholder="mock" />
        </div>
      </div>
      <div v-if="createLocalError" class="override-error">{{ createLocalError }}</div>
      <template #footer>
        <Button label="取消" text @click="createVisible = false" />
        <Button label="创建活动" :loading="createSubmitting" :disabled="createSubmitting" @click="submitCreate" />
      </template>
    </Dialog>

    <!-- 阶段查询 -->
    <Dialog
      v-model:visible="phaseVisible"
      modal
      :draggable="false"
      header="活动阶段查询"
      class="events-dialog"
      :style="{ width: 'min(560px, calc(100vw - 32px))' }"
    >
      <div class="phase-body">
        <div class="form-row">
          <span class="form-label">活动</span>
          <span class="form-value">{{ phaseTarget ? phaseTarget.event_name : '—' }}</span>
        </div>
        <div class="form-row">
          <span class="form-label">查询时刻</span>
          <input v-model="phaseTs" type="datetime-local" class="native-input" />
        </div>
        <Button label="查询阶段" icon="pi pi-search" outlined :loading="phaseLoading" @click="queryPhase" />
        <div v-if="phaseError" class="override-error">{{ phaseError }}</div>
        <div v-if="phaseResult" class="phase-result">
          <div class="phase-result-row">
            <span>所处阶段</span>
            <Tag :value="phaseResult.phase_label" :severity="phaseSeverity(phaseResult.phase)" />
          </div>
          <div class="phase-result-row">
            <span>影响增幅</span>
            <span v-if="phaseResult.uplift === null || phaseResult.uplift === undefined" class="uplift-unknown">
              <Tag value="数据不足" severity="warn" />
            </span>
            <span v-else class="cell-number">+{{ Number(phaseResult.uplift).toFixed(1) }}%</span>
          </div>
          <div class="phase-result-row">
            <span>置信度</span>
            <Tag :value="confidenceLabel(phaseResult.confidence)" :severity="confidenceSeverity(phaseResult.confidence)" />
          </div>
          <div class="phase-result-row">
            <span>说明</span>
            <span class="phase-note">{{ phaseResult.note || '—' }}</span>
          </div>
        </div>
      </div>
      <template #footer>
        <Button label="关闭" text @click="phaseVisible = false" />
      </template>
    </Dialog>

    <!-- 删除确认 -->
    <Dialog
      v-model:visible="deleteVisible"
      modal
      :draggable="false"
      header="删除活动"
      class="events-dialog"
      :style="{ width: 'min(460px, calc(100vw - 32px))' }"
    >
      <div class="delete-body">
        <div>确认删除活动「{{ deleteTarget ? deleteTarget.event_name : '' }}」？删除后不可恢复。</div>
        <div v-if="deleteError" class="override-error">{{ deleteError }}</div>
      </div>
      <template #footer>
        <Button label="取消" text @click="deleteVisible = false" />
        <Button label="确认删除" severity="danger" :loading="deleteSubmitting" @click="submitDelete" />
      </template>
    </Dialog>
  </div>
</template>

<script setup lang="ts">
/**
 * 活动日历页（阶段四交付物）。
 * 页面文案全部为中文硬编码，按需求不接入 vue-i18n。
 * 需求硬约束：expected_uplift 为 null 时显示「数据不足 / 低置信度」，不得显示为 0；
 * target_uris 为空数组表示覆盖应用下全部 URL，不得理解为「无影响」。
 */
import { computed, onMounted, ref } from 'vue';
import Button from 'primevue/button';
import Column from 'primevue/column';
import DataTable from 'primevue/datatable';
import Dialog from 'primevue/dialog';
import Dropdown from 'primevue/dropdown';
import InputNumber from 'primevue/inputnumber';
import InputText from 'primevue/inputtext';
import Message from 'primevue/message';
import Tag from 'primevue/tag';
import Textarea from 'primevue/textarea';
import { useToast } from 'primevue/usetoast';
import {
  EventsApiError,
  createEvent,
  deleteEvent,
  fetchEventPhase,
  fetchEvents,
  initMockEvents,
} from '@/api/events';
import type { BusinessEvent, EventPhaseResult } from '@/api/events';
import {
  BEIJING_OFFSET_MS,
  DAY_MS,
  beijingDayKey,
  beijingDayRange,
  formatBeijingDateTime,
  parseTimestamp,
  toBeijingParts,
} from '@/utils';

/** 日历单元格上的活动标记 */
interface CalendarMark {
  key: string;
  phase: string;
  event: BusinessEvent;
}

/** 日历单元格 */
interface CalendarCell {
  key: string;
  date: Date;
  day: number;
  inMonth: boolean;
  isToday: boolean;
  marks: CalendarMark[];
}

/** 新建活动表单（时间字段为 datetime-local 的本地字符串） */
interface EventForm {
  event_id: string;
  event_name: string;
  event_type: string;
  start_time: string;
  end_time: string;
  preheat_start: string;
  preheat_end: string;
  cooldown_end: string;
  target_apps_text: string;
  target_uris_text: string;
  business_type: string;
  impact_level: string;
  expected_uplift: number | null;
  historical_event_id: string;
  event_owner: string;
  data_source: string;
  status: string;
}

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

/** 置信度语义色 */
const CONFIDENCE_SEVERITIES: Record<string, string> = {
  high: 'success',
  medium: 'info',
  low: 'warn',
};

/** 阶段中文标签 */
const PHASE_LABELS: Record<string, string> = {
  preheat: '预热期',
  active: '正式期',
  cooldown: '回落期',
  none: '不受影响',
};

/** 阶段语义色 */
const PHASE_SEVERITIES: Record<string, string> = {
  preheat: 'warn',
  active: 'danger',
  cooldown: 'info',
  none: 'secondary',
};

/** 星期一开头的星期标签 */
const WEEKDAY_LABELS = ['一', '二', '三', '四', '五', '六', '日'];

/** 全量拉取上限 */
const EVENTS_LIMIT = 500;

const toast = useToast();

const events = ref<BusinessEvent[]>([]);
const listLoading = ref(false);
const listError = ref('');
const initLoading = ref(false);
const statusFilter = ref<string>('');
const typeFilter = ref<string>('');
const appFilter = ref<string>('');

const calendarMonth = ref<Date>(startOfMonth(currentBeijingDate()));
const selectedDayKey = ref<string>(beijingDayKey(Date.now()));

const createVisible = ref(false);
const createSubmitting = ref(false);
const createErrorMessage = ref('');
const createErrors = ref<string[]>([]);
const createLocalError = ref('');

const phaseVisible = ref(false);
const phaseTarget = ref<BusinessEvent | null>(null);
const phaseTs = ref<string>(toLocalInputValue(new Date()));
const phaseLoading = ref(false);
const phaseError = ref('');
const phaseResult = ref<EventPhaseResult | null>(null);

const deleteVisible = ref(false);
const deleteTarget = ref<BusinessEvent | null>(null);
const deleteSubmitting = ref(false);
const deleteError = ref('');

/** 状态筛选项 */
const statusOptions = [
  { label: '全部状态', value: '' },
  { label: '草稿', value: 'draft' },
  { label: '已确认', value: 'confirmed' },
  { label: '已完成', value: 'completed' },
  { label: '已取消', value: 'cancelled' },
];

/** 类型筛选项 */
const typeOptions = [
  { label: '全部类型', value: '' },
  { label: '营销活动', value: 'marketing' },
  { label: '批处理', value: 'batch' },
  { label: '促销活动', value: 'promotion' },
  { label: '上线发布', value: 'launch' },
  { label: '节假日', value: 'holiday' },
];

/** 影响等级选项 */
const impactOptions = [
  { label: '低', value: 'low' },
  { label: '中', value: 'medium' },
  { label: '高', value: 'high' },
];

/** 新建活动表单初值 */
const createEmptyForm = (): EventForm => ({
  event_id: '',
  event_name: '',
  event_type: 'marketing',
  start_time: '',
  end_time: '',
  preheat_start: '',
  preheat_end: '',
  cooldown_end: '',
  target_apps_text: '',
  target_uris_text: '',
  business_type: '',
  impact_level: 'medium',
  expected_uplift: null,
  historical_event_id: '',
  event_owner: '',
  data_source: 'mock',
  status: 'confirmed',
});

const form = ref<EventForm>(createEmptyForm());

/** 应用名筛选项：从活动数据中提取去重 */
const appOptions = computed(() => {
  const names = new Set<string>();
  events.value.forEach((event) => {
    (event.target_apps || []).forEach((app) => {
      if (app) {
        names.add(app);
      }
    });
  });
  const sorted = Array.from(names).sort((a, b) => a.localeCompare(b, 'zh-CN'));
  return [{ label: '全部应用', value: '' }, ...sorted.map((name) => ({ label: name, value: name }))];
});

/** 本地筛选后的活动列表 */
const filteredEvents = computed(() =>
  events.value.filter((event) => {
    if (statusFilter.value && event.status !== statusFilter.value) {
      return false;
    }
    if (typeFilter.value && event.event_type !== typeFilter.value) {
      return false;
    }
    if (appFilter.value && !(event.target_apps || []).includes(appFilter.value)) {
      return false;
    }
    return true;
  })
);

/** Mock 数据源活动数量 */
const mockEventCount = computed(
  () => events.value.filter((event) => String(event.data_source || '').toLowerCase() === 'mock').length
);

/** 顶部统计卡片数据 */
const stats = computed(() => {
  const now = Date.now();
  const totalCount = events.value.length;
  const confirmedCount = events.value.filter((event) => event.status === 'confirmed').length;
  const runningCount = events.value.filter((event) => {
    const start = parseTime(event.start_time);
    const end = parseTime(event.end_time);
    return start !== null && end !== null && now >= start && now <= end;
  }).length;
  const highImpactCount = events.value.filter((event) => event.impact_level === 'high').length;
  const unknownUpliftCount = events.value.filter(
    (event) => event.expected_uplift === null || event.expected_uplift === undefined
  ).length;
  return { totalCount, confirmedCount, runningCount, highImpactCount, unknownUpliftCount };
});

/** 日历月份标题 */
const calendarMonthText = computed(
  () => `${calendarMonth.value.getFullYear()} 年 ${calendarMonth.value.getMonth() + 1} 月`
);

/** 日历单元格（6 行 × 7 列，周一开头） */
const calendarCells = computed<CalendarCell[]>(() => {
  const month = calendarMonth.value;
  const first = startOfMonth(month);
  // 周一为一周起点：getDay() 周日为 0，需换算成周一为 0
  const offset = (first.getDay() + 6) % 7;
  const gridStart = new Date(first.getTime() - offset * DAY_MS);
  const today = beijingDayKey(Date.now());
  const cells: CalendarCell[] = [];
  for (let index = 0; index < 42; index += 1) {
    const date = new Date(gridStart.getTime() + index * DAY_MS);
    // 按北京时间自然日取绝对区间，保证染色分日与后端 +08:00 口径一致
    const range = beijingDayRange(date.getFullYear(), date.getMonth() + 1, date.getDate());
    const dayStart = range.start;
    const dayEnd = range.end;
    const marks: CalendarMark[] = [];
    events.value.forEach((event) => {
      const phase = phaseOnDay(event, dayStart, dayEnd);
      if (phase) {
        marks.push({ key: `${event.event_id}-${phase}`, phase, event });
      }
    });
    const key = dayKey(date);
    cells.push({
      key,
      date,
      day: date.getDate(),
      inMonth: date.getMonth() === month.getMonth() && date.getFullYear() === month.getFullYear(),
      isToday: key === today,
      marks,
    });
  }
  return cells;
});

/** 选中日期的展示文案 */
const selectedDayText = computed(() => {
  const cell = calendarCells.value.find((item) => item.key === selectedDayKey.value);
  if (!cell) {
    return '当日活动';
  }
  return `${cell.date.getFullYear()} 年 ${cell.date.getMonth() + 1} 月 ${cell.date.getDate()} 日 当日活动`;
});

/** 选中日期的活动清单 */
const selectedDayEvents = computed<CalendarMark[]>(() => {
  const cell = calendarCells.value.find((item) => item.key === selectedDayKey.value);
  if (!cell) {
    return [];
  }
  // 同一活动可能命中多个阶段，正式期优先展示
  const priority: Record<string, number> = { active: 3, preheat: 2, cooldown: 1, none: 0 };
  const best = new Map<string, CalendarMark>();
  cell.marks.forEach((mark) => {
    const current = best.get(mark.event.event_id);
    if (!current || (priority[mark.phase] || 0) > (priority[current.phase] || 0)) {
      best.set(mark.event.event_id, mark);
    }
  });
  return Array.from(best.values());
});

/**
 * 取某月 1 号零点。
 * @param date 日期
 */
function startOfMonth(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), 1);
}

/**
 * 取当前时刻对应的「北京时间日历日」。
 * 用本地 Date 承载，仅用于日历网格的年/月/日取值，
 * 时区换算统一走 utils 中的东八区工具函数。
 */
function currentBeijingDate(): Date {
  const parts = toBeijingParts(Date.now());
  return new Date(parts.year, parts.month - 1, parts.day);
}

/**
 * 生成日期 key（本地日期，yyyy-mm-dd）。
 * @param date 日期
 */
function dayKey(date: Date): string {
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/**
 * 解析 ISO 时间字符串为时间戳，解析失败返回 null。
 * 统一使用 new Date(...) 解析，后端返回的 Z / +00:00 / +08:00 三种后缀均可正确识别，
 * 不做任何字符串切片，避免时区后缀不一致导致的时间偏移。
 * @param value ISO 时间字符串
 */
function parseTime(value: string | null | undefined): number | null {
  return parseTimestamp(value);
}

/**
 * 判断活动在指定自然日所处的阶段（用于日历染色）。
 * 优先命中正式期，其次预热期，最后回落期；均不命中返回 null。
 * @param event 活动对象
 * @param dayStart 当日零点时间戳
 * @param dayEnd 当日 23:59:59 时间戳
 */
function phaseOnDay(event: BusinessEvent, dayStart: number, dayEnd: number): string | null {
  const start = parseTime(event.start_time);
  const end = parseTime(event.end_time);
  if (start !== null && end !== null && start <= dayEnd && end >= dayStart) {
    return 'active';
  }
  const preheatStart = parseTime(event.preheat_start);
  const preheatEnd = parseTime(event.preheat_end);
  if (preheatStart !== null && preheatEnd !== null && preheatStart <= dayEnd && preheatEnd >= dayStart) {
    return 'preheat';
  }
  const cooldownEnd = parseTime(event.cooldown_end);
  if (end !== null && cooldownEnd !== null && end < dayEnd && cooldownEnd >= dayStart) {
    return 'cooldown';
  }
  return null;
}

/**
 * 时间格式化：统一按东八区（北京时间）展示，避免受浏览器 / 容器时区影响。
 * @param value ISO 时间字符串
 */
function formatDateTime(value: string | null | undefined): string {
  return formatBeijingDateTime(value);
}

/**
 * 把时间转成 datetime-local 输入框需要的字符串（北京时间墙上时间，yyyy-MM-ddTHH:mm）。
 * @param date 日期
 */
function toLocalInputValue(date: Date): string {
  const parts = toBeijingParts(date.getTime());
  const pad = (input: number) => String(input).padStart(2, '0');
  return `${parts.year}-${pad(parts.month)}-${pad(parts.day)}T${pad(parts.hour)}:${pad(parts.minute)}`;
}

/**
 * 把 datetime-local 的字符串（按北京时间录入）转成绝对时刻的 ISO8601。
 * 即：把「北京时间墙上时间」换算为 UTC 时刻，后端再统一转 +08:00 存储。
 * @param value yyyy-MM-ddTHH:mm 格式的北京时间
 */
function toIsoString(value: string): string {
  if (!value) {
    return '';
  }
  const matched = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(value);
  if (!matched) {
    return '';
  }
  const year = Number(matched[1]);
  const month = Number(matched[2]);
  const day = Number(matched[3]);
  const hour = Number(matched[4]);
  const minute = Number(matched[5]);
  const ms = Date.UTC(year, month - 1, day, hour, minute) - BEIJING_OFFSET_MS;
  if (Number.isNaN(ms)) {
    return '';
  }
  return new Date(ms).toISOString();
}

/**
 * 活动类型中文标签。
 * @param value 类型值
 */
function typeLabel(value: string): string {
  return TYPE_LABELS[value] || value || '—';
}

/**
 * 活动状态中文标签。
 * @param value 状态值
 */
function statusLabel(value: string): string {
  return STATUS_LABELS[value] || value || '—';
}

/**
 * 活动状态语义色。
 * @param value 状态值
 */
function statusSeverity(value: string): string {
  return STATUS_SEVERITIES[value] || 'secondary';
}

/**
 * 影响等级中文标签。
 * @param value 等级值
 */
function impactLabel(value: string): string {
  return IMPACT_LABELS[value] || value || '—';
}

/**
 * 影响等级语义色。
 * @param value 等级值
 */
function impactSeverity(value: string): string {
  return IMPACT_SEVERITIES[value] || 'secondary';
}

/**
 * 置信度中文标签。
 * @param value 置信度值
 */
function confidenceLabel(value: string): string {
  return CONFIDENCE_LABELS[value] || value || '—';
}

/**
 * 置信度语义色。
 * @param value 置信度值
 */
function confidenceSeverity(value: string): string {
  return CONFIDENCE_SEVERITIES[value] || 'secondary';
}

/**
 * 阶段中文标签。
 * @param value 阶段值
 */
function phaseLabel(value: string): string {
  return PHASE_LABELS[value] || value || '—';
}

/**
 * 阶段语义色。
 * @param value 阶段值
 */
function phaseSeverity(value: string): string {
  return PHASE_SEVERITIES[value] || 'secondary';
}

/**
 * 加载活动列表。
 */
async function loadEvents() {
  listLoading.value = true;
  listError.value = '';
  try {
    const result = await fetchEvents({ limit: EVENTS_LIMIT, offset: 0 });
    events.value = result.events;
    if (appFilter.value && !appOptions.value.some((item) => item.value === appFilter.value)) {
      appFilter.value = '';
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : '获取活动列表失败';
    events.value = [];
    listError.value = `${message}（请确认活动服务已启动：http://127.0.0.1:8091）`;
  } finally {
    listLoading.value = false;
  }
}

/**
 * 初始化 Mock 活动数据。
 */
async function handleInitMock() {
  initLoading.value = true;
  try {
    const result = await initMockEvents();
    toast.add({
      severity: 'success',
      summary: 'Mock 数据已初始化',
      detail: `已写入 ${result.count} 个演示活动`,
      life: 3000,
    });
    await loadEvents();
  } catch (error) {
    const message = error instanceof Error ? error.message : '初始化 Mock 活动失败';
    toast.add({ severity: 'error', summary: '初始化失败', detail: message, life: 5000 });
  } finally {
    initLoading.value = false;
  }
}

/**
 * 月份切换。
 * @param delta -1 上一月，1 下一月
 */
function shiftMonth(delta: number) {
  const current = calendarMonth.value;
  calendarMonth.value = new Date(current.getFullYear(), current.getMonth() + delta, 1);
}

/** 回到当前月份（按北京时间） */
function goCurrentMonth() {
  const now = currentBeijingDate();
  calendarMonth.value = startOfMonth(now);
  selectedDayKey.value = beijingDayKey(Date.now());
}

/**
 * 选中日历某一天。
 * @param cell 日历单元格
 */
function selectDay(cell: CalendarCell) {
  selectedDayKey.value = cell.key;
  if (!cell.inMonth) {
    calendarMonth.value = startOfMonth(cell.date);
  }
}

/** 打开新建活动弹窗 */
function openCreateDialog() {
  form.value = createEmptyForm();
  createErrorMessage.value = '';
  createErrors.value = [];
  createLocalError.value = '';
  createVisible.value = true;
}

/**
 * 把多行/逗号分隔文本解析为数组。
 * @param text 输入文本
 */
function parseListText(text: string): string[] {
  return String(text || '')
    .split(/[\n,，;；]/)
    .map((item) => item.trim())
    .filter((item) => Boolean(item));
}

/**
 * 提交新建活动。
 */
async function submitCreate() {
  const payload = form.value;
  createErrorMessage.value = '';
  createErrors.value = [];

  const localErrors: string[] = [];
  if (!payload.event_name.trim()) {
    localErrors.push('活动名称不能为空');
  }
  const startTime = toIsoString(payload.start_time);
  const endTime = toIsoString(payload.end_time);
  if (!startTime || !endTime) {
    localErrors.push('活动开始时间与结束时间不能为空');
  } else if (new Date(startTime).getTime() >= new Date(endTime).getTime()) {
    localErrors.push('活动时间不合法：start_time 必须早于 end_time');
  }
  const targetApps = parseListText(payload.target_apps_text);
  if (targetApps.length === 0) {
    localErrors.push('受影响应用（target_apps）不能为空，至少需指定一个应用');
  }
  if (localErrors.length > 0) {
    createLocalError.value = localErrors.join('；');
    createErrorMessage.value = '活动参数校验失败';
    createErrors.value = localErrors;
    return;
  }
  createLocalError.value = '';

  createSubmitting.value = true;
  try {
    const result = await createEvent({
      event_id: payload.event_id.trim() || undefined,
      event_name: payload.event_name.trim(),
      event_type: payload.event_type,
      start_time: startTime,
      end_time: endTime,
      preheat_start: toIsoString(payload.preheat_start) || null,
      preheat_end: toIsoString(payload.preheat_end) || null,
      cooldown_end: toIsoString(payload.cooldown_end) || null,
      target_apps: targetApps,
      target_uris: parseListText(payload.target_uris_text),
      business_type: payload.business_type.trim() || undefined,
      impact_level: payload.impact_level,
      expected_uplift: payload.expected_uplift === null ? null : Number(payload.expected_uplift),
      historical_event_id: payload.historical_event_id.trim() || null,
      event_owner: payload.event_owner.trim() || undefined,
      data_source: payload.data_source.trim() || 'mock',
      status: payload.status,
    });
    createVisible.value = false;
    toast.add({
      severity: 'success',
      summary: '活动已创建',
      detail: result.message || `${result.event.event_name} 已写入活动库`,
      life: 3000,
    });
    await loadEvents();
  } catch (error) {
    if (error instanceof EventsApiError) {
      createErrorMessage.value = error.message || '活动参数校验失败';
      createErrors.value = error.errors.length > 0 ? error.errors : [error.message];
    } else {
      const message = error instanceof Error ? error.message : '创建活动失败';
      createErrorMessage.value = '创建活动失败';
      createErrors.value = [message];
    }
  } finally {
    createSubmitting.value = false;
  }
}

/**
 * 打开阶段查询弹窗。
 * @param event 活动对象
 */
function openPhaseDialog(event: BusinessEvent) {
  phaseTarget.value = event;
  phaseTs.value = toLocalInputValue(new Date());
  phaseResult.value = null;
  phaseError.value = '';
  phaseVisible.value = true;
}

/**
 * 查询活动在指定时刻的阶段。
 */
async function queryPhase() {
  const target = phaseTarget.value;
  if (!target) {
    return;
  }
  const iso = toIsoString(phaseTs.value);
  if (!iso) {
    phaseError.value = '请选择合法的查询时刻';
    return;
  }
  phaseError.value = '';
  phaseLoading.value = true;
  try {
    phaseResult.value = await fetchEventPhase(target.event_id, iso);
  } catch (error) {
    const message = error instanceof Error ? error.message : '查询活动阶段失败';
    phaseError.value = message;
    phaseResult.value = null;
  } finally {
    phaseLoading.value = false;
  }
}

/**
 * 打开删除确认弹窗。
 * @param event 活动对象
 */
function openDeleteDialog(event: BusinessEvent) {
  deleteTarget.value = event;
  deleteError.value = '';
  deleteVisible.value = true;
}

/**
 * 提交删除。
 */
async function submitDelete() {
  const target = deleteTarget.value;
  if (!target) {
    return;
  }
  deleteSubmitting.value = true;
  deleteError.value = '';
  try {
    const result = await deleteEvent(target.event_id);
    deleteVisible.value = false;
    toast.add({
      severity: 'success',
      summary: '活动已删除',
      detail: result.message || `${target.event_name} 已删除`,
      life: 3000,
    });
    await loadEvents();
  } catch (error) {
    const message = error instanceof Error ? error.message : '删除活动失败';
    deleteError.value = message;
    toast.add({ severity: 'error', summary: '删除失败', detail: message, life: 5000 });
  } finally {
    deleteSubmitting.value = false;
  }
}

onMounted(() => {
  void loadEvents();
});
</script>

<style scoped lang="scss">
.forecast-events-page {
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
  max-width: 680px;
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

.stat-card.running .stat-card-icon {
  background: rgba(239, 68, 68, 0.14);
  color: #dc2626;
}

.stat-card.high .stat-card-icon {
  background: rgba(245, 158, 11, 0.16);
  color: #d97706;
}

.stat-card.low .stat-card-icon {
  background: rgba(100, 116, 139, 0.16);
  color: #64748b;
}

.calendar-card {
  padding: 18px 20px 20px;
}

.calendar-nav {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 6px;
}

.calendar-month {
  min-width: 96px;
  text-align: center;
  font-size: 14px;
  font-weight: 700;
  color: var(--text);
}

.calendar-legend {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 12px;
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

.legend-dot.preheat {
  background: #f59e0b;
}

.legend-dot.active {
  background: #ef4444;
}

.legend-dot.cooldown {
  background: #3b82f6;
}

.legend-muted {
  color: var(--muted);
}

.calendar-grid {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 6px;
}

.calendar-weekday {
  text-align: center;
  font-size: 12px;
  font-weight: 700;
  color: var(--muted);
  padding-bottom: 4px;
}

.calendar-cell {
  min-height: 74px;
  border: 1px solid var(--border);
  border-radius: var(--radius-xs);
  background: var(--panel-muted);
  padding: 6px 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  cursor: pointer;
  transition: border-color 0.2s ease, box-shadow 0.2s ease, background 0.2s ease;
}

.calendar-cell:hover {
  border-color: rgba(var(--primary-color-rgb), 0.42);
}

.calendar-cell.is-outside {
  opacity: 0.45;
}

.calendar-cell.is-today {
  border-color: rgba(var(--primary-color-rgb), 0.6);
}

.calendar-cell.is-selected {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(var(--primary-color-rgb), 0.14);
  background: var(--panel);
}

.calendar-day {
  font-size: 12px;
  font-weight: 700;
  color: var(--text);
}

.calendar-marks {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

.calendar-mark {
  width: 100%;
  height: 6px;
  border-radius: var(--radius-pill);
  display: block;
}

.calendar-mark.preheat {
  background: #f59e0b;
}

.calendar-mark.active {
  background: #ef4444;
}

.calendar-mark.cooldown {
  background: #3b82f6;
}

.calendar-mark-more {
  font-size: 10px;
  color: var(--muted);
}

.calendar-day-panel {
  margin-top: 16px;
  border-top: 1px dashed var(--border);
  padding-top: 14px;
}

.calendar-day-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--text);
  margin-bottom: 10px;
}

.calendar-day-empty {
  font-size: 13px;
  color: var(--muted);
  padding: 6px 0;
}

.calendar-day-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.calendar-day-item {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 13px;
  padding: 8px 12px;
  border-radius: var(--radius-xs);
  background: var(--panel-muted);
}

.calendar-day-name {
  font-weight: 600;
  color: var(--text);
}

.calendar-day-range {
  color: var(--muted);
  font-variant-numeric: tabular-nums;
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
  min-width: 180px;
}

.filter-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--muted);
}

.filter-dropdown {
  min-width: 180px;
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

.cell-uri {
  display: inline-block;
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}

.event-name-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.event-sub {
  font-size: 11px;
  color: var(--muted);
}

.event-phase-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 12px;
  color: var(--muted);
}

.chip-list {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.uplift-unknown {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.uplift-hint {
  font-size: 11px;
  color: var(--muted);
}

.row-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

.table-empty {
  padding: 28px 0;
  text-align: center;
  font-size: 13px;
  color: var(--muted);
}

.form-error-box {
  border: 1px solid rgba(239, 68, 68, 0.28);
  background: rgba(239, 68, 68, 0.08);
  border-radius: var(--radius-xs);
  padding: 12px 14px;
  margin-bottom: 14px;
}

.form-error-title {
  font-size: 13px;
  font-weight: 700;
  color: #b91c1c;
  margin-bottom: 6px;
}

.form-error-list {
  margin: 0;
  padding-left: 18px;
  font-size: 12px;
  line-height: 1.7;
  color: #991b1b;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 18px;
}

.form-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-row.span-2 {
  grid-column: span 2;
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

.form-control,
.native-input {
  width: 100%;
}

.native-input {
  padding: 9px 12px;
  border-radius: var(--radius-xs);
  border: 1px solid var(--border);
  background: var(--input-bg);
  color: var(--text);
  font-size: 13px;
  font-family: inherit;
  outline: none;
}

.native-input:focus {
  border-color: rgba(var(--primary-color-rgb), 0.6);
  box-shadow: 0 0 0 3px rgba(var(--primary-color-rgb), 0.15);
}

.override-error {
  margin-top: 12px;
  font-size: 12px;
  color: var(--error-color);
}

.phase-body,
.delete-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.form-value {
  font-size: 13px;
  color: var(--text);
  word-break: break-all;
}

.phase-result {
  display: flex;
  flex-direction: column;
  gap: 10px;
  border-top: 1px dashed var(--border);
  padding-top: 12px;
}

.phase-result-row {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 13px;
}

.phase-result-row > span:first-child {
  flex: 0 0 72px;
  color: var(--muted);
}

.phase-note {
  color: var(--text);
  line-height: 1.6;
}

:deep(.events-table .p-datatable-thead > tr > th) {
  background: var(--panel-muted);
  font-size: 12px;
  white-space: nowrap;
}

:deep(.events-table .p-datatable-tbody > tr > td) {
  font-size: 13px;
  padding: 8px 12px;
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

  .stat-grid,
  .form-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .form-row.span-2 {
    grid-column: span 1;
  }

  .calendar-cell {
    min-height: 58px;
  }
}
</style>
