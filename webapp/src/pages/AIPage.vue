<template>
  <div class="ai-page">
    <div class="ai-header">
      <h1>🤖 AI 智能分析</h1>
      <p class="ai-description">
        使用人工智能技术进行异常流量检测、智能查询和自动化报表生成
      </p>
    </div>

    <div class="ai-content">
      <!-- 智能查询 -->
      <div class="ai-card">
        <div class="ai-card-header">
          <h2>💬 智能查询</h2>
          <p class="ai-card-description">用自然语言查询访问数据</p>
        </div>
        <div class="query-section">
          <div class="query-examples">
            <span class="examples-label">示例问题：</span>
            <Button
              v-for="example in exampleQuestions"
              :key="example"
              :label="example"
              @click="queryQuestion = example; handleQuery()"
              class="example-button"
              outlined
              size="small"
            />
          </div>
          <div class="query-input-wrapper">
            <InputText
              v-model="queryQuestion"
              placeholder="输入问题，例如：今天有多少 PV？"
              class="query-input"
              @keyup.enter="handleQuery"
            />
            <Button
              label="查询"
              icon="pi pi-search"
              :loading="queryLoading"
              @click="handleQuery"
              class="query-button"
            />
          </div>
          <div v-if="queryResult" class="query-result">
            <div class="query-answer">
              <span class="answer-badge" :class="queryResult.llm_generated ? 'is-llm' : 'is-raw'">
                {{ queryResult.llm_generated ? 'AI 生成' : '原始数据' }}
              </span>
              <span class="answer-text">{{ queryResult.answer }}</span>
            </div>

            <div v-if="queryHighlights.length" class="query-blocks">
              <div class="query-block block-highlight">
                <h4>🔍 关键发现</h4>
                <ul>
                  <li v-for="(h, idx) in queryHighlights" :key="idx">{{ h }}</li>
                </ul>
              </div>
            </div>

            <div v-if="queryResult.business_insight" class="query-block block-business">
              <h4>📈 业务解读</h4>
              <p>{{ queryResult.business_insight }}</p>
            </div>

            <div v-if="queryOpsAdvice.length" class="query-block block-ops">
              <h4>🛠️ 运维建议</h4>
              <ol class="advice-list">
                <li v-for="(a, idx) in queryOpsAdvice" :key="idx">{{ a }}</li>
              </ol>
            </div>

            <div v-if="queryRiskAlerts.length" class="query-block block-risk">
              <h4>⚠️ 风险提示</h4>
              <ul class="risk-list">
                <li v-for="(r, idx) in queryRiskAlerts" :key="idx">{{ r }}</li>
              </ul>
            </div>

            <details v-if="queryResult.sql" class="query-sql-toggle">
              <summary>查看 SQL（AI 生成）</summary>
              <code class="query-sql">{{ queryResult.sql }}</code>
            </details>
            <div v-if="queryResult.data && queryResult.data.length > 0" class="query-data">
              <DataTable :value="queryResult.data" paginator :rows="10" class="query-table">
                <Column v-for="col in Object.keys(queryResult.data[0])" :key="col" :field="col" :header="col" />
              </DataTable>
            </div>
          </div>
        </div>
      </div>

      <!-- 异常检测 -->
      <div class="ai-card">
        <div class="ai-card-header">
          <h2>🚨 异常流量检测</h2>
          <p class="ai-card-description">自动识别 CC 攻击、爬虫和扫描器</p>
        </div>
        <div class="anomaly-section">
          <div class="anomaly-intro">
            <p>点击"开始检测"按钮，分析过去指定时间段内的访问日志，识别异常流量模式。</p>
          </div>
          <div class="anomaly-controls">
            <div class="anomaly-control-item">
              <label>检测时长（小时）</label>
              <InputNumber v-model="anomalyHours" :min="1" :max="168" />
            </div>
            <Button
              label="开始检测"
              icon="pi pi-exclamation-triangle"
              :loading="anomalyLoading"
              @click="handleAnomalyDetect"
              class="anomaly-button"
            />
          </div>
          <div v-if="anomalyResult && anomalyResult.anomalies.length > 0" class="anomaly-result">
            <div class="anomaly-summary">
              发现 <strong>{{ anomalyResult.total }}</strong> 个异常行为
              <span v-if="anomalyResult.llmAnalyzed" class="llm-badge">
                AI 已研判 {{ anomalyResult.llmAnalyzed }} 项
              </span>
            </div>

            <!-- heavy_hitter 聚合图表 -->
            <div v-if="hitterChart.length > 0" class="hitter-aggregate">
              <div class="hitter-aggregate-header">
                <h4>📊 超高占比来源 TOP {{ hitterChart.length }}</h4>
                <span class="hitter-total-share">
                  合计占总流量 <strong>{{ (anomalyResult.hitterTotalShare || 0).toFixed(2) }}%</strong>
                </span>
              </div>

              <!-- IP 占比条形图 -->
              <div class="hitter-bars">
                <div v-for="h in hitterChart" :key="h.ip" class="hitter-bar-row">
                  <span class="hitter-bar-label">{{ h.ip }}</span>
                  <div class="hitter-bar-track">
                    <div
                      class="hitter-bar-fill"
                      :class="getShareBarTone(h.share_pct)"
                      :style="{ width: Math.min(100, (h.share_pct / maxShare) * 100) + '%' }"
                    >
                      <span class="hitter-bar-pct">{{ h.share_pct.toFixed(2) }}%</span>
                    </div>
                  </div>
                  <span class="hitter-bar-count">{{ Number(h.request_count || 0).toLocaleString() }}</span>
                </div>
              </div>

              <!-- 各 IP 访问的 TOP URL -->
              <div class="hitter-urls">
                <details v-for="h in hitterChart" :key="h.ip" class="hitter-url-block">
                  <summary>{{ h.ip }} — {{ (h.top_urls || []).length }} 个高频 URL</summary>
                  <ul>
                    <li v-for="u in h.top_urls" :key="u.url">
                      <code>{{ u.url }}</code>
                      <span class="hitter-url-count">{{ Number(u.count).toLocaleString() }} 次</span>
                    </li>
                  </ul>
                </details>
              </div>

              <!-- 汇总式 LLM 研判 -->
              <div v-if="anomalyResult.hitterSummary?.risk_analysis" class="hitter-summary-judgement">
                <div class="anomaly-judgement">
                  <h5>⚠️ 整体风险研判</h5>
                  <p>{{ anomalyResult.hitterSummary.risk_analysis }}</p>
                </div>
                <div v-if="anomalyResult.hitterSummary.impact" class="anomaly-judgement">
                  <h5>🎯 整体影响面</h5>
                  <p>{{ anomalyResult.hitterSummary.impact }}</p>
                </div>
                <div v-if="anomalyResult.hitterSummary.actions?.length" class="anomaly-actions">
                  <h5>🛡️ 整体处置建议（按紧急程度）</h5>
                  <ol class="action-list">
                    <li v-for="(act, idx) in anomalyResult.hitterSummary.actions" :key="idx">{{ act }}</li>
                  </ol>
                </div>
                <span v-if="anomalyResult.hitterSummary.confidence" class="confidence-tag">
                  置信度 {{ (anomalyResult.hitterSummary.confidence * 100).toFixed(0) }}%
                </span>
              </div>
            </div>

            <!-- 非 heavy_hitter 类型保持单卡展示 -->
            <div class="anomaly-list">
              <div
                v-for="anomaly in anomalyResult.anomalies.filter(a => a.type !== 'heavy_hitter')"
                :key="anomaly.id ?? anomaly.source_ips?.join()"
                class="anomaly-item"
              >
                <div class="anomaly-item-header">
                  <span class="anomaly-type">
                    {{ anomaly.title || getAnomalyTypeLabel(anomaly.type) }}
                  </span>
                  <div class="anomaly-tags">
                    <Tag :value="getSeverityLabel(anomaly.severity)" :severity="getSeverityColor(anomaly.severity)" />
                    <span v-if="anomaly.confidence" class="confidence-tag">
                      置信度 {{ (anomaly.confidence * 100).toFixed(0) }}%
                    </span>
                  </div>
                </div>
                <div class="anomaly-item-content">
                  <div class="anomaly-facts">
                    <div class="anomaly-stat">
                      <span class="label">类型：</span>
                      <span class="value">{{ getAnomalyTypeLabel(anomaly.type) }}</span>
                    </div>
                    <div class="anomaly-stat">
                      <span class="label">请求数：</span>
                      <span class="value">{{ Number(anomaly.request_count || 0).toLocaleString() }}</span>
                    </div>
                    <div class="anomaly-stat">
                      <span class="label">时间范围：</span>
                      <span class="value">{{ formatTime(anomaly.time_range) }}</span>
                    </div>
                    <div class="anomaly-stat">
                      <span class="label">源 IP：</span>
                      <span class="value ip-list">{{ (anomaly.source_ips || []).join('、') || '-' }}</span>
                    </div>
                  </div>

                  <div v-if="anomaly.risk_analysis" class="anomaly-judgement">
                    <h5>⚠️ 风险研判</h5>
                    <p>{{ anomaly.risk_analysis }}</p>
                  </div>

                  <div v-if="anomaly.impact" class="anomaly-judgement">
                    <h5>🎯 影响面</h5>
                    <p>{{ anomaly.impact }}</p>
                  </div>

                  <div v-if="anomaly.actions && anomaly.actions.length" class="anomaly-actions">
                    <h5>🛡️ 处置建议（按紧急程度）</h5>
                    <ol class="action-list">
                      <li v-for="(act, idx) in anomaly.actions" :key="idx">{{ act }}</li>
                    </ol>
                  </div>

                  <details v-if="anomaly.evidence && anomaly.evidence.length" class="anomaly-evidence-toggle">
                    <summary>原始检测证据（{{ anomaly.evidence.length }} 条）</summary>
                    <ul>
                      <li v-for="evidence in anomaly.evidence" :key="evidence">{{ evidence }}</li>
                    </ul>
                  </details>
                </div>
              </div>
            </div>
          </div>
          <div v-else-if="anomalyResult && anomalyResult.anomalies.length === 0" class="anomaly-empty">
            <i class="pi pi-check-circle"></i>
            <span>未发现异常流量</span>
          </div>
        </div>
      </div>

      <!-- 报表生成 -->
      <div class="ai-card">
        <div class="ai-card-header">
          <h2>📊 智能报表</h2>
          <p class="ai-card-description">自动生成日报、周报、月报</p>
        </div>
        <div class="report-section">
          <div class="report-intro">
            <p>选择报表类型和日期，点击"生成报表"按钮创建详细的访问分析报告。</p>
          </div>
          <div class="report-controls">
            <div class="report-control-item">
              <label>报表类型</label>
              <Dropdown
                v-model="reportType"
                :options="reportTypeOptions"
                optionLabel="label"
                optionValue="value"
                placeholder="选择类型"
              />
            </div>
            <div class="report-control-item">
              <label>日期</label>
              <DatePicker v-model="reportDate" dateFormat="yy-mm-dd" placeholder="选择日期" />
            </div>
            <Button
              label="生成报表"
              icon="pi pi-file"
              :loading="reportLoading"
              @click="handleGenerateReport(false)"
              class="report-button"
            />
            <Button
              v-if="reportResult"
              label="重新生成"
              icon="pi pi-refresh"
              :loading="reportLoading"
              @click="handleGenerateReport(true)"
              class="report-refresh-button"
              outlined
              severity="secondary"
            />
          </div>
          <div v-if="reportResult" class="report-result">
            <div class="report-header">
              <h3>{{ getReportTitle(reportResult) }}</h3>
              <Tag :value="getReportTypeLabel(reportResult.type)" />
            </div>
            <div v-if="reportResult.period || reportResult.generated_at" class="report-meta">
              <span v-if="reportResult.period">统计周期：{{ formatTime(reportResult.period) }}</span>
              <span v-if="reportResult.generated_at">生成时间：{{ formatTime(reportResult.generated_at) }}</span>
            </div>
            <div v-if="reportResult.summary" class="report-summary">
              {{ reportResult.summary }}
            </div>
            <div class="report-metrics" v-if="scalarMetrics.length">
              <div v-for="item in scalarMetrics" :key="item.key" class="metric-card">
                <div class="metric-label">{{ item.label }}</div>
                <div class="metric-value" :class="item.tone">{{ item.display }}</div>
              </div>
            </div>

            <div v-if="hourlyBars.length" class="report-section">
              <h4>24 小时 PV 分布</h4>
              <div class="hourly-chart">
                <div
                  v-for="bar in hourlyBars"
                  :key="bar.hour"
                  class="hourly-col"
                  :title="`${bar.hour}:00 — ${bar.value.toLocaleString()} PV`"
                >
                  <div class="hourly-bar" :style="{ height: bar.height + '%' }"></div>
                  <div class="hourly-tick">{{ bar.hour }}</div>
                </div>
              </div>
            </div>

            <div v-if="statusList.length" class="report-section">
              <h4>状态码分布</h4>
              <div class="dist-list">
                <div v-for="item in statusList" :key="item.label" class="dist-row">
                  <span class="dist-label">{{ item.label }}</span>
                  <div class="dist-track">
                    <div class="dist-fill" :class="item.tone" :style="{ width: item.pct + '%' }"></div>
                  </div>
                  <span class="dist-value">{{ item.value.toLocaleString() }}（{{ item.pct }}%）</span>
                </div>
              </div>
            </div>

            <div v-if="deviceList.length" class="report-section">
              <h4>设备分布</h4>
              <div class="dist-list">
                <div v-for="item in deviceList" :key="item.label" class="dist-row">
                  <span class="dist-label">{{ item.label }}</span>
                  <div class="dist-track">
                    <div class="dist-fill" :style="{ width: item.pct + '%' }"></div>
                  </div>
                  <span class="dist-value">{{ item.value.toLocaleString() }}（{{ item.pct }}%）</span>
                </div>
              </div>
            </div>

            <div v-for="list in topLists" :key="list.title" class="report-section">
              <h4>{{ list.title }}</h4>
              <ol class="top-list">
                <li v-for="(item, idx) in list.items" :key="idx">
                  <span class="top-label" :title="item.label">{{ item.label }}</span>
                  <span class="top-count">{{ item.count.toLocaleString() }}</span>
                </li>
              </ol>
            </div>
            <div v-if="reportResult.insights && reportResult.insights.length" class="report-insights">
              <h4>关键洞察</h4>
              <ul>
                <li v-for="(insight, idx) in reportResult.insights" :key="idx">{{ insight }}</li>
              </ul>
            </div>
            <div v-if="reportResult.recommendations && reportResult.recommendations.length" class="report-recommendations">
              <h4>💡 优化建议</h4>
              <ol class="recommendation-list">
                <li v-for="(rec, idx) in reportResult.recommendations" :key="idx">{{ rec }}</li>
              </ol>
            </div>
            <div v-if="reportResult.predictions && reportResult.predictions.length" class="report-predictions">
              <h4>趋势预测</h4>
              <div class="prediction-list">
                <div v-for="(pred, idx) in reportResult.predictions" :key="idx" class="prediction-item">
                  <span class="prediction-metric">{{ getMetricLabel(pred.metric) }}</span>
                  <span class="prediction-value">{{ formatMetricValue(pred.value) }}</span>
                  <span class="prediction-trend" :class="pred.trend">{{ getTrendLabel(pred.trend) }}（置信度 {{ (pred.confidence * 100).toFixed(0) }}%）</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { useToast } from 'primevue/usetoast';
import InputText from 'primevue/inputtext';
import Button from 'primevue/button';
import DataTable from 'primevue/datatable';
import Column from 'primevue/column';
import Tag from 'primevue/tag';
import Dropdown from 'primevue/dropdown';
import DatePicker from 'primevue/datepicker';
import InputNumber from 'primevue/inputnumber';
import { aiQuery, detectAnomalies, generateReport, fetchAnomalies } from '@/api/ai';

// 在 setup 函数内部调用 useToast() 确保 PrimeVue 已初始化
const toast = useToast();

// 示例问题列表
const exampleQuestions = [
  '今天有多少 PV？',
  '过去 24 小时的独立访客数是多少？',
  '哪个 URL 的访问量最高？',
  '过去 1 小时的错误率是多少？',
];

// 智能查询
const queryQuestion = ref('');
const queryLoading = ref(false);
const queryResult = ref<any>(null);

// 兜底：后端可能返回 null / 非数组，统一转成数组后再渲染
const asStringArray = (value: any): string[] =>
  Array.isArray(value) ? value.filter((v) => v !== null && v !== undefined && String(v).trim() !== '') : [];

const queryHighlights = computed(() => asStringArray(queryResult.value?.highlights));
const queryOpsAdvice = computed(() => asStringArray(queryResult.value?.ops_advice));
const queryRiskAlerts = computed(() => asStringArray(queryResult.value?.risk_alerts));

// 页面加载时显示欢迎提示
onMounted(() => {
  toast.add({
    severity: 'info',
    summary: '欢迎使用 AI 智能分析',
    detail: '点击示例问题开始查询，或输入自定义问题',
    life: 8000,
  });
});

const handleQuery = async () => {
  if (!queryQuestion.value.trim()) {
    toast.add({
      severity: 'warn',
      summary: '提示',
      detail: '请输入查询问题',
      life: 3000,
    });
    return;
  }

  queryLoading.value = true;
  try {
    const result = await aiQuery(queryQuestion.value);
    queryResult.value = result;
    if (!result.success) {
      toast.add({
        severity: 'error',
        summary: '查询失败',
        detail: result.answer || 'AI 查询失败，请稍后重试',
        life: 5000,
      });
    }
  } catch (error) {
    console.error('AI query error:', error);
    toast.add({
      severity: 'error',
      summary: '查询失败',
      detail: 'AI 服务不可用，请稍后重试',
      life: 5000,
    });
  } finally {
    queryLoading.value = false;
  }
};

// 异常检测
const anomalyHours = ref(24);
const anomalyLoading = ref(false);
const anomalyResult = ref<any>(null);

const handleAnomalyDetect = async () => {
  anomalyLoading.value = true;
  try {
    const result = await detectAnomalies(anomalyHours.value);
    anomalyResult.value = result;
    if (result.anomalies.length > 0) {
      toast.add({
        severity: 'warn',
        summary: '发现异常',
        detail: `检测到 ${result.total} 个异常流量行为`,
        life: 5000,
      });
    } else {
      toast.add({
        severity: 'success',
        summary: '检测完成',
        detail: '未发现异常流量',
        life: 3000,
      });
    }
  } catch (error) {
    console.error('Anomaly detection error:', error);
    toast.add({
      severity: 'error',
      summary: '检测失败',
      detail: '异常检测失败，请稍后重试',
      life: 5000,
    });
  } finally {
    anomalyLoading.value = false;
  }
};

// heavy_hitter 聚合图表数据
const hitterChart = computed(() => {
  const hitters = anomalyResult.value?.heavyHitters;
  if (!Array.isArray(hitters)) return [];
  return hitters.map((h: any) => ({
    ip: h.ip || '未知',
    share_pct: Number(h.share_pct || 0),
    request_count: Number(h.request_count || 0),
    top_urls: Array.isArray(h.top_urls) ? h.top_urls : [],
  })).sort((a: any, b: any) => b.share_pct - a.share_pct);
});

// 条形图最大占比（用于归一化宽度），取 TOP1 占比与 20% 的较大值
const maxShare = computed(() => {
  const items = hitterChart.value;
  if (items.length === 0) return 20;
  return Math.max(...items.map((h: any) => h.share_pct), 20);
});

// 报表生成
const reportType = ref<'daily' | 'weekly' | 'monthly'>('daily');
const reportDate = ref(new Date());
const reportLoading = ref(false);
const reportResult = ref<any>(null);

const reportTypeOptions = [
  { label: '日报', value: 'daily' },
  { label: '周报', value: 'weekly' },
  { label: '月报', value: 'monthly' },
];

const handleGenerateReport = async (refresh = false) => {
  reportLoading.value = true;
  try {
    const dateStr = reportDate.value ? formatDate(reportDate.value) : undefined;
    const result = await generateReport(reportType.value, dateStr, refresh);
    reportResult.value = result;
    toast.add({
      severity: 'success',
      summary: '报表生成成功',
      detail: `${getReportTypeLabel(reportType.value)}已生成${refresh ? '（已刷新）' : ''}`,
      life: 3000,
    });
  } catch (error) {
    console.error('Report generation error:', error);
    toast.add({
      severity: 'error',
      summary: '生成失败',
      detail: '报表生成失败，请稍后重试',
      life: 5000,
    });
  } finally {
    reportLoading.value = false;
  }
};

// 工具函数
const getAnomalyTypeLabel = (type: string): string => {
  const labels: Record<string, string> = {
    cc_attack: 'CC 攻击',
    crawler: '爬虫',
    scanner: '扫描器',
    heavy_hitter: '超高占比来源',
    error_burst: '错误率突增',
  };
  return labels[type] || type;
};

const getSeverityLabel = (severity: string): string => {
  const labels: Record<string, string> = {
    high: '高',
    medium: '中',
    low: '低',
  };
  return labels[severity] || severity;
};

const getSeverityColor = (severity: string): 'danger' | 'warning' | 'success' => {
  if (severity === 'high') return 'danger';
  if (severity === 'medium') return 'warning';
  return 'success';
};

// 根据占比大小返回条形图颜色
const getShareBarTone = (sharePct: number): string => {
  if (sharePct >= 20) return 'tone-danger';
  if (sharePct >= 10) return 'tone-warn';
  if (sharePct >= 5) return 'tone-warn';
  return 'tone-info';
};

const formatTime = (timeStr: string): string => {
  try {
    return new Date(timeStr).toLocaleString('zh-CN');
  } catch {
    return timeStr;
  }
};

const formatDate = (date: Date): string => {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
};

const getReportTypeLabel = (type: string): string => {
  const labels: Record<string, string> = {
    daily: '日报',
    weekly: '周报',
    monthly: '月报',
  };
  return labels[type] || type;
};

const getReportTitle = (report: any): string => {
  if (report?.title) {
    return report.title;
  }
  const typeLabel = getReportTypeLabel(report?.type);
  if (report?.period) {
    return `${typeLabel}（${formatTime(report.period)}）`;
  }
  return `${typeLabel}报告`;
};

const getTrendLabel = (trend: string): string => {
  const labels: Record<string, string> = {
    up: '上升',
    down: '下降',
    stable: '平稳',
  };
  return labels[trend] || trend;
};

interface MetricItem {
  key: string;
  label: string;
  display: string;
  tone?: string;
}

// 后端 metrics 的完整中文标签映射（避免直接把英文 key 渲染到界面）
const METRIC_LABELS: Record<string, string> = {
  total_pv: '总访问量 PV',
  total_uv: '独立访客 UV',
  total_requests: '总请求数',
  error_count: '错误请求数',
  error_rate: '错误率',
  avg_response_time: '平均响应时间',
  p95_response_time: 'P95 响应时间',
  total_traffic_mb: '总流量',
  peak_hour: '流量高峰时段',
  pv_growth: 'PV 环比',
  prev_day_pv: '前一日 PV',
  status_2xx: '2xx 成功',
  status_3xx: '3xx 重定向',
  status_4xx: '4xx 客户端错误',
  status_5xx: '5xx 服务端错误',
  pv: 'PV',
  uv: 'UV',
};

// 卡片区只展示这些标量指标，顺序固定
const SCALAR_METRIC_KEYS = [
  'total_pv',
  'total_uv',
  'total_requests',
  'error_count',
  'error_rate',
  'avg_response_time',
  'p95_response_time',
  'total_traffic_mb',
  'peak_hour',
  'pv_growth',
  'prev_day_pv',
];

const getMetricLabel = (key: string): string => METRIC_LABELS[key] || key;

const toNumber = (value: any): number => {
  const n = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(n) ? n : 0;
};

// 按指标语义格式化，避免对象/数组被 String() 成 [object Object]
const formatMetric = (key: string, value: any): string => {
  const n = toNumber(value);
  switch (key) {
    case 'error_rate':
    case 'pv_growth':
      return `${n >= 0 ? '' : ''}${n.toFixed(2)}%`;
    case 'avg_response_time':
    case 'p95_response_time':
      return `${n.toFixed(2)} ms`;
    case 'total_traffic_mb':
      return n >= 1024 ? `${(n / 1024).toFixed(2)} GB` : `${n.toFixed(2)} MB`;
    case 'peak_hour':
      return n >= 0 ? `${String(n).padStart(2, '0')}:00` : '无';
    default:
      return n >= 10000 ? `${(n / 10000).toFixed(1)} 万` : n.toLocaleString();
  }
};

const metricsOf = (report: any): Record<string, any> =>
  report?.metrics && typeof report.metrics === 'object' ? report.metrics : {};

const scalarMetrics = computed<MetricItem[]>(() => {
  const metrics = metricsOf(reportResult.value);
  return SCALAR_METRIC_KEYS.filter((key) => metrics[key] !== undefined).map((key) => {
    const n = toNumber(metrics[key]);
    let tone = '';
    if (key === 'error_rate') tone = n > 5 ? 'tone-danger' : n > 1 ? 'tone-warn' : 'tone-ok';
    if (key === 'pv_growth') tone = n > 0 ? 'tone-ok' : n < 0 ? 'tone-danger' : '';
    return { key, label: METRIC_LABELS[key] || key, display: formatMetric(key, metrics[key]), tone };
  });
});

const statusList = computed(() => {
  const metrics = metricsOf(reportResult.value);
  const raw = [
    { label: '2xx 成功', value: toNumber(metrics.status_2xx), tone: 'tone-ok' },
    { label: '3xx 重定向', value: toNumber(metrics.status_3xx), tone: 'tone-info' },
    { label: '4xx 客户端错误', value: toNumber(metrics.status_4xx), tone: 'tone-warn' },
    { label: '5xx 服务端错误', value: toNumber(metrics.status_5xx), tone: 'tone-danger' },
  ];
  const total = raw.reduce((sum, item) => sum + item.value, 0);
  if (total <= 0) return [];
  return raw.map((item) => ({
    ...item,
    pct: ((item.value / total) * 100).toFixed(1),
  }));
});

const deviceList = computed(() => {
  const metrics = metricsOf(reportResult.value);
  const devices = metrics.devices;
  if (!devices || typeof devices !== 'object') return [];
  const entries = Object.entries(devices).map(([label, value]) => ({
    label,
    value: toNumber(value),
  }));
  const total = entries.reduce((sum, item) => sum + item.value, 0);
  if (total <= 0) return [];
  return entries
    .sort((a, b) => b.value - a.value)
    .map((item) => ({ ...item, pct: ((item.value / total) * 100).toFixed(1) }));
});

const hourlyBars = computed(() => {
  const metrics = metricsOf(reportResult.value);
  const hourly = metrics.hourly_pv;
  if (!Array.isArray(hourly) || hourly.length === 0) return [];
  const max = Math.max(...hourly.map((v) => toNumber(v)), 1);
  return hourly.map((value, hour) => ({
    hour,
    value: toNumber(value),
    height: Math.round((toNumber(value) / max) * 100),
  }));
});

const topLists = computed(() => {
  const metrics = metricsOf(reportResult.value);
  const defs = [
    { key: 'top_urls', title: '热门页面 TOP10' },
    { key: 'top_ips', title: '活跃访客 IP TOP10' },
    { key: 'top_referers', title: '来源渠道 TOP5' },
  ];
  return defs
    .map(({ key, title }) => {
      const raw = metrics[key];
      if (!Array.isArray(raw)) return null;
      const items = raw
        .map((item: any) => ({
          label: String(item?.label ?? '-'),
          count: toNumber(item?.count),
        }))
        .filter((item) => item.count > 0);
      return items.length ? { title, items } : null;
    })
    .filter(Boolean) as Array<{ title: string; items: { label: string; count: number }[] }>;
});

const formatMetricValue = (value: any): string => {
  const n = toNumber(value);
  return n >= 10000 ? `${(n / 10000).toFixed(1)} 万` : n.toLocaleString();
};

const formatReportContent = (content: string): string => {
  if (!content) return '';
  const escapeHtml = (text: string): string =>
    text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  const lines = content.split('\n');
  const out: string[] = [];
  let inUl = false;
  let inOl = false;

  const closeLists = () => {
    if (inUl) { out.push('</ul>'); inUl = false; }
    if (inOl) { out.push('</ol>'); inOl = false; }
  };

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      closeLists();
      continue;
    }
    if (line.startsWith('# ')) {
      closeLists();
      out.push(`<h2>${escapeHtml(line.slice(2))}</h2>`);
    } else if (line.startsWith('## ')) {
      closeLists();
      out.push(`<h3>${escapeHtml(line.slice(3))}</h3>`);
    } else if (line.startsWith('### ')) {
      closeLists();
      out.push(`<h4>${escapeHtml(line.slice(4))}</h4>`);
    } else if (line.startsWith('> ')) {
      closeLists();
      out.push(`<blockquote>${escapeHtml(line.slice(2))}</blockquote>`);
    } else if (/^[-*]\s+/.test(line)) {
      if (inOl) { out.push('</ol>'); inOl = false; }
      if (!inUl) { out.push('<ul>'); inUl = true; }
      out.push(`<li>${escapeHtml(line.replace(/^[-*]\s+/, ''))}</li>`);
    } else if (/^\d+[.、]\s*/.test(line)) {
      if (inUl) { out.push('</ul>'); inUl = false; }
      if (!inOl) { out.push('<ol>'); inOl = true; }
      out.push(`<li>${escapeHtml(line.replace(/^\d+[.、]\s*/, ''))}</li>`);
    } else {
      closeLists();
      out.push(`<p>${escapeHtml(line)}</p>`);
    }
  }
  closeLists();
  return out.join('');
};
</script>

<style scoped>
.ai-page {
  padding: 24px;
  max-width: 1400px;
  margin: 0 auto;
}

.ai-header {
  margin-bottom: 32px;
}

.ai-header h1 {
  font-size: 28px;
  font-weight: 600;
  margin-bottom: 8px;
  color: var(--text-color);
}

.ai-description {
  color: var(--text-color-secondary);
  font-size: 14px;
}

.ai-content {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.ai-card {
  background: var(--surface-card);
  border-radius: 12px;
  padding: 24px;
  box-shadow: var(--card-shadow);
}

.ai-card-header {
  margin-bottom: 20px;
}

.ai-card-header h2 {
  font-size: 20px;
  font-weight: 600;
  margin-bottom: 4px;
  color: var(--text-color);
}

.ai-card-description {
  color: var(--text-color-secondary);
  font-size: 13px;
}

/* 智能查询样式 */
.query-examples {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-bottom: 12px;
  padding: 12px;
  background: var(--surface-ground);
  border-radius: 8px;
}

.examples-label {
  font-size: 13px;
  color: var(--text-color-secondary);
  font-weight: 500;
}

.example-button {
  font-size: 12px;
  padding: 6px 12px;
}

.query-input-wrapper {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}

.query-input {
  flex: 1;
  font-size: 14px;
}

.query-button {
  min-width: 100px;
}

.query-result {
  background: var(--surface-ground);
  border-radius: 8px;
  padding: 16px;
}

.query-answer {
  margin-bottom: 12px;
  font-size: 14px;
  line-height: 1.6;
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.answer-badge {
  flex-shrink: 0;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
  font-weight: 600;
  line-height: 1.7;
}

.answer-badge.is-llm {
  background: rgba(var(--primary-color-rgb), 0.12);
  color: var(--primary-strong);
}

.answer-badge.is-raw {
  background: var(--surface-border);
  color: var(--text-color-secondary);
}

.answer-text {
  color: var(--text-color);
}

/* 智能查询：业务解读 / 运维建议 / 风险提示 */
.query-block {
  margin-bottom: 12px;
  padding: 14px 16px;
  border-radius: 8px;
  border: 1px solid var(--surface-border);
  background: var(--surface-card);
}

.query-block h4 {
  font-size: 13px;
  font-weight: 600;
  margin: 0 0 10px;
  color: var(--text-color);
}

.query-block p {
  margin: 0;
  font-size: 13px;
  line-height: 1.8;
  color: var(--text-color-secondary);
}

.query-block ul,
.query-block ol {
  margin: 0;
  padding-left: 20px;
  font-size: 13px;
  line-height: 1.8;
  color: var(--text-color-secondary);
}

.query-block li {
  margin-bottom: 4px;
}

.block-business {
  border-left: 3px solid var(--primary-color);
}

.block-ops {
  border-left: 3px solid #0ea5e9;
}

.block-highlight {
  border-left: 3px solid #8b5cf6;
}

.block-risk {
  border-left: 3px solid #ef4444;
  background: rgba(239, 68, 68, 0.06);
}

.risk-list {
  color: #b91c1c !important;
}

.advice-list li {
  margin-bottom: 6px;
}

.query-sql-toggle {
  margin-bottom: 12px;
  font-size: 13px;
}

.query-sql-toggle summary {
  cursor: pointer;
  color: var(--text-color-secondary);
  font-size: 12px;
  user-select: none;
}

.query-sql-toggle summary:hover {
  color: var(--primary-color);
}

.query-sql {
  margin-top: 4px;
}

.query-sql code {
  background: var(--surface-card);
  padding: 8px 12px;
  border-radius: 6px;
  display: block;
  margin-top: 4px;
  font-family: 'Courier New', monospace;
  color: var(--primary-color);
}

.query-table {
  margin-top: 12px;
}

/* 异常检测样式 */
.anomaly-intro,
.report-intro {
  margin-bottom: 16px;
  padding: 12px;
  background: var(--surface-ground);
  border-radius: 6px;
  color: var(--text-color-secondary);
  font-size: 13px;
  line-height: 1.6;
}

.anomaly-intro p,
.report-intro p {
  margin: 0;
}

.anomaly-controls {
  display: flex;
  gap: 16px;
  align-items: flex-end;
  margin-bottom: 20px;
}

.anomaly-control-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.anomaly-control-item label {
  font-size: 13px;
  color: var(--text-color-secondary);
}

.anomaly-button {
  min-width: 120px;
}

.anomaly-result {
  margin-top: 16px;
}

.anomaly-summary {
  font-size: 14px;
  margin-bottom: 16px;
  padding: 12px;
  background: var(--primary-color-light);
  border-radius: 6px;
  border-left: 4px solid var(--primary-color);
}

.anomaly-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.anomaly-item {
  background: var(--surface-ground);
  border-radius: 8px;
  padding: 16px;
  border: 1px solid var(--surface-border);
}

.anomaly-item-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--surface-border);
}

.anomaly-type {
  font-weight: 600;
  font-size: 14px;
  color: var(--text-color);
}

.anomaly-item-content {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.anomaly-stat {
  font-size: 13px;
  color: var(--text-color-secondary);
}

.anomaly-stat .label {
  font-weight: 500;
  margin-right: 4px;
}

.anomaly-stat .value {
  color: var(--text-color);
}

/* 异常检测：LLM 研判 / 影响面 / 处置建议 */
.anomaly-facts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 6px 16px;
}

/* heavy_hitter 占比条形图 */
.anomaly-share-chart {
  padding: 12px 14px;
  background: var(--surface-ground);
  border-radius: 8px;
  margin-bottom: 8px;
}

.share-bar-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.share-label {
  font-family: 'Courier New', monospace;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-color);
  min-width: 140px;
  word-break: break-all;
  text-align: right;
}

.share-bar-track {
  flex: 1;
  background: var(--surface-border);
  border-radius: 4px;
  overflow: hidden;
}

.share-bar-fill {
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding-right: 8px;
  min-width: 40px;
  border-radius: 4px;
  transition: width 0.3s ease;
}

.share-bar-fill.tone-danger { background: #ef4444; }
.share-bar-fill.tone-warn { background: #f59e0b; }
.share-bar-fill.tone-info { background: #3b82f6; }
.share-bar-fill.tone-ok { background: #22c55e; }

.share-pct {
  font-size: 11px;
  font-weight: 700;
  color: #fff;
  white-space: nowrap;
}

.share-chart-meta {
  display: flex;
  justify-content: space-between;
  margin-top: 6px;
  font-size: 11px;
  color: var(--text-color-secondary);
}

/* heavy_hitter 聚合图表 */
.hitter-aggregate {
  margin-bottom: 16px;
  padding: 16px;
  background: var(--surface-ground);
  border-radius: 8px;
}

.hitter-aggregate-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.hitter-aggregate-header h4 {
  margin: 0;
  font-size: 14px;
}

.hitter-total-share {
  font-size: 12px;
  color: var(--text-color-secondary);
}

.hitter-total-share strong {
  color: var(--text-color);
}

.hitter-bars {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.hitter-bar-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.hitter-bar-label {
  font-family: 'Courier New', monospace;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-color);
  min-width: 130px;
  word-break: break-all;
  text-align: right;
  flex-shrink: 0;
}

.hitter-bar-track {
  flex: 1;
  background: var(--surface-border);
  border-radius: 4px;
  overflow: hidden;
}

.hitter-bar-fill {
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding-right: 8px;
  min-width: 40px;
  border-radius: 4px;
  transition: width 0.3s ease;
}

.hitter-bar-fill.tone-danger { background: #ef4444; }
.hitter-bar-fill.tone-warn { background: #f59e0b; }
.hitter-bar-fill.tone-info { background: #3b82f6; }
.hitter-bar-fill.tone-ok { background: #22c55e; }

.hitter-bar-pct {
  font-size: 11px;
  font-weight: 700;
  color: #fff;
  white-space: nowrap;
}

.hitter-bar-count {
  font-size: 11px;
  color: var(--text-color-secondary);
  min-width: 50px;
  text-align: right;
  flex-shrink: 0;
}

.hitter-urls {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.hitter-url-block {
  background: var(--surface-card);
  border-radius: 6px;
  overflow: hidden;
}

.hitter-url-block summary {
  cursor: pointer;
  padding: 8px 12px;
  font-size: 12px;
  color: var(--text-color);
  user-select: none;
}

.hitter-url-block summary:hover {
  color: var(--primary-color);
}

.hitter-url-block ul {
  list-style: none;
  padding: 8px 12px;
  margin: 0;
}

.hitter-url-block li {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 0;
  font-size: 12px;
}

.hitter-url-block code {
  font-family: 'Courier New', monospace;
  color: var(--text-color);
  word-break: break-all;
  flex: 1;
}

.hitter-url-count {
  color: var(--text-color-secondary);
  white-space: nowrap;
  margin-left: 12px;
}

.hitter-summary-judgement {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--surface-border);
}

.anomaly-stat .value.ip-list {
  word-break: break-all;
}

.anomaly-tags {
  display: flex;
  align-items: center;
  gap: 8px;
}

.confidence-tag {
  font-size: 11px;
  color: var(--text-color-secondary);
  background: var(--surface-border);
  padding: 2px 8px;
  border-radius: 10px;
}

.anomaly-judgement {
  margin-top: 12px;
  padding: 12px 14px;
  background: var(--surface-ground);
  border-radius: 6px;
  border-left: 3px solid #f59e0b;
}

.anomaly-judgement h5 {
  font-size: 12px;
  font-weight: 600;
  margin: 0 0 6px;
  color: var(--text-color);
}

.anomaly-judgement p {
  margin: 0;
  font-size: 13px;
  line-height: 1.8;
  color: var(--text-color-secondary);
}

.anomaly-actions {
  margin-top: 12px;
  padding: 12px 14px;
  background: rgba(14, 165, 233, 0.07);
  border-radius: 6px;
  border-left: 3px solid #0ea5e9;
}

.anomaly-actions h5 {
  font-size: 12px;
  font-weight: 600;
  margin: 0 0 8px;
  color: var(--text-color);
}

.action-list {
  margin: 0;
  padding-left: 20px;
  font-size: 13px;
  line-height: 1.8;
  color: var(--text-color-secondary);
}

.action-list li {
  margin-bottom: 6px;
}

.anomaly-evidence-toggle {
  margin-top: 12px;
  font-size: 12px;
}

.anomaly-evidence-toggle summary {
  cursor: pointer;
  color: var(--text-color-secondary);
  user-select: none;
  padding: 4px 0;
}

.anomaly-evidence-toggle ul {
  margin: 6px 0 0;
  padding-left: 20px;
  color: var(--text-color-secondary);
  line-height: 1.8;
}

.llm-badge {
  margin-left: 10px;
  font-size: 12px;
  color: var(--primary-strong);
  background: rgba(var(--primary-color-rgb), 0.1);
  padding: 2px 10px;
  border-radius: 10px;
}

.anomaly-empty {
  text-align: center;
  padding: 40px 20px;
  color: var(--text-color-secondary);
}

.anomaly-empty i {
  font-size: 48px;
  color: var(--success-color);
  display: block;
  margin-bottom: 12px;
}

/* 报表生成样式 */
.report-controls {
  display: flex;
  gap: 16px;
  align-items: flex-end;
  margin-bottom: 20px;
  flex-wrap: wrap;
}

.report-control-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 200px;
}

.report-control-item label {
  font-size: 13px;
  color: var(--text-color-secondary);
}

.report-button {
  min-width: 120px;
}

.report-refresh-button {
  min-width: 120px;
}

.report-result {
  margin-top: 16px;
}

.report-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  padding-bottom: 16px;
  border-bottom: 2px solid var(--surface-border);
}

.report-header h3 {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-color);
  margin: 0;
}

.report-summary {
  font-size: 14px;
  line-height: 1.6;
  color: var(--text-color-secondary);
  margin-bottom: 20px;
  padding: 16px;
  background: var(--surface-ground);
  border-radius: 8px;
}

.report-metrics {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 16px;
  margin-bottom: 20px;
}

.metric-card {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 8px;
  padding: 16px;
  text-align: center;
}

.metric-label {
  font-size: 12px;
  color: var(--text-color-secondary);
  margin-bottom: 8px;
}

.metric-value {
  font-size: 24px;
  font-weight: 600;
  color: var(--primary-color);
}

.report-content {
  font-size: 14px;
  line-height: 1.8;
  color: var(--text-color);
  padding: 16px;
  background: var(--surface-card);
  border-radius: 8px;
  border: 1px solid var(--surface-border);
}

.report-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  font-size: 12px;
  color: var(--text-color-secondary);
  margin-bottom: 12px;
}

.report-insights,
.report-predictions {
  margin-bottom: 20px;
  padding: 16px;
  background: var(--surface-ground);
  border-radius: 8px;
}

.report-insights h4,
.report-predictions h4 {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-color);
  margin: 0 0 12px;
}

.report-insights ul {
  margin: 0;
  padding-left: 20px;
  color: var(--text-color-secondary);
  font-size: 13px;
  line-height: 1.7;
}

.report-insights li {
  margin-bottom: 6px;
}

.prediction-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.prediction-item {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 13px;
}

.prediction-metric {
  font-weight: 500;
  color: var(--text-color);
  min-width: 80px;
}

.prediction-value {
  font-weight: 600;
  color: var(--primary-color);
  min-width: 60px;
}

.prediction-trend {
  font-size: 12px;
  padding: 2px 10px;
  border-radius: var(--radius-pill);
}

.prediction-trend.up {
  background: rgba(239, 68, 68, 0.12);
  color: #ef4444;
}

.prediction-trend.down {
  background: rgba(34, 197, 94, 0.12);
  color: #22c55e;
}

.prediction-trend.stable {
  background: var(--primary-soft);
  color: var(--primary-strong);
}

.report-recommendations {
  margin-bottom: 20px;
  padding: 16px;
  background: rgba(var(--primary-color-rgb), 0.06);
  border: 1px solid rgba(var(--primary-color-rgb), 0.22);
  border-radius: 8px;
}

.report-recommendations h4 {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-color);
  margin: 0 0 12px;
}

.recommendation-list {
  margin: 0;
  padding-left: 20px;
  color: var(--text-color-secondary);
  font-size: 13px;
  line-height: 1.7;
}

.recommendation-list li {
  margin-bottom: 6px;
}

/* ---- 结构化数据区块（避免复合对象直接渲染造成显示错乱） ---- */
.report-section {
  margin-bottom: 20px;
  padding: 16px;
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 8px;
}

.report-section h4 {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-color);
  margin: 0 0 14px;
}

.hourly-chart {
  display: flex;
  align-items: flex-end;
  gap: 3px;
  height: 132px;
}

.hourly-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  align-items: center;
  height: 100%;
  min-width: 0;
}

.hourly-bar {
  width: 100%;
  min-height: 2px;
  background: linear-gradient(180deg, var(--primary-strong), var(--primary-color));
  border-radius: 3px 3px 0 0;
  transition: height 0.3s ease;
}

.hourly-tick {
  margin-top: 4px;
  font-size: 10px;
  color: var(--text-color-secondary);
}

.dist-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.dist-row {
  display: grid;
  grid-template-columns: 96px 1fr auto;
  align-items: center;
  gap: 12px;
}

.dist-label {
  font-size: 12px;
  color: var(--text-color-secondary);
}

.dist-track {
  height: 8px;
  background: var(--surface-border);
  border-radius: 4px;
  overflow: hidden;
}

.dist-fill {
  height: 100%;
  background: var(--primary-color);
  border-radius: 4px;
  transition: width 0.3s ease;
}

.dist-fill.tone-ok { background: #22c55e; }
.dist-fill.tone-info { background: #3b82f6; }
.dist-fill.tone-warn { background: #f59e0b; }
.dist-fill.tone-danger { background: #ef4444; }

.dist-value {
  font-size: 12px;
  color: var(--text-color);
  font-variant-numeric: tabular-nums;
}

.top-list {
  margin: 0;
  padding-left: 20px;
  font-size: 13px;
  line-height: 1.9;
  color: var(--text-color-secondary);
}

.top-list li {
  display: flex;
  justify-content: space-between;
  gap: 16px;
}

.top-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.top-count {
  color: var(--text-color);
  font-variant-numeric: tabular-nums;
}

.metric-value.tone-ok { color: #16a34a; }
.metric-value.tone-warn { color: #d97706; }
.metric-value.tone-danger { color: #dc2626; }

.report-content :deep(h2) {
  font-size: 17px;
  font-weight: 700;
  color: var(--text-color);
  margin: 18px 0 10px;
}

.report-content :deep(h3) {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-color);
  margin: 14px 0 8px;
}

.report-content :deep(h4) {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-color);
  margin: 12px 0 6px;
}

.report-content :deep(blockquote) {
  margin: 0 0 12px;
  padding: 8px 12px;
  border-left: 3px solid var(--primary-color);
  background: var(--surface-ground);
  border-radius: 4px;
  color: var(--text-color-secondary);
  font-size: 12px;
}

.report-content :deep(p) {
  margin: 0 0 10px;
  font-size: 13px;
  color: var(--text-color-secondary);
  line-height: 1.8;
}

.report-content :deep(ul),
.report-content :deep(ol) {
  margin: 0 0 12px;
  padding-left: 22px;
  color: var(--text-color-secondary);
  font-size: 13px;
  line-height: 1.8;
}

.report-content :deep(li) {
  margin-bottom: 6px;
}
</style>
