# 阶段二 + 阶段三 交付文档

> Nginx 交易量预测与 AI 业务态势分析模块 V1.1
> 日期：2026-11-02 · 环境：Docker Compose（PG 已拆为独立容器）+ conda `workbuddy` 运行预测服务

---

## 零、基础设施变更：PostgreSQL 拆分为独立容器

原架构为单体镜像内置 PG17（仅监听容器内 `127.0.0.1:5432`，宿主机不可达），预测服务无法连库。

| 项 | 说明 |
|---|---|
| 新增服务 | `db`（postgres:16），端口 `5432:5432` 映射宿主机 |
| 数据目录 | `docker_local/pgdata`（bind mount），由 pg_dump 从原库迁移 |
| 主服务改造 | `nginxpulse` 通过 `DB_DSN` 指向 `nginxpulse_pg`，entrypoint 自动禁用内置 PG |
| 验证 | 启动日志 `use external postgres: yes (host=nginxpulse_pg)`；8088 返回 200；PG healthy |

数据完整性核验：日志表 49469 行、聚合表、URL 表行数与原库一致。

---

## 一、阶段二：预测准入过滤模块

### 1.1 代码变更清单

| 文件 | 说明 |
|---|---|
| `forecast-service/app/mock/generator.py` | Mock 时序生成器：70 天、5min 粒度、31 个对象（core/standard/batch/lowfreq/cold），叠加日内+周周期+趋势+活动峰值 |
| `forecast-service/app/eligibility/rules.py` | 准入规则配置（阈值全部可配置，不硬编码） |
| `forecast-service/app/eligibility/engine.py` | 资格引擎：13 项特征 + 周期检测（周哑变量回归 R²）+ 8 种状态判定 + 6 维资格评分 |
| `forecast-service/app/storage/eligibility_store.py` | 存储层：PG 优先 + 内存后备双模式 |
| `forecast-service/app/api/main.py` | 6 个资格接口 |
| `forecast-service/sql/001_eligibility.sql` | `forecast_eligibility` / `_history` / `_rules` 三张表 |
| `webapp/src/api/forecast.ts` | 前端 API 层（独立 axios 实例 + 完整 TS 类型） |
| `webapp/src/pages/ForecastObjectsPage.vue` | 预测对象管理页面（约 900 行，中文硬编码，未用 i18n） |
| `webapp/src/router/index.ts` | 新增 `/forecast-objects` 路由 |
| `webapp/src/App.vue` | 侧边栏新增「预测对象管理」菜单 |

### 1.2 接口说明

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/forecast/v1/eligibility/evaluate` | 评估单个对象资格 |
| GET | `/api/forecast/v1/eligibility/list` | 分页/状态/应用筛选查询 |
| POST | `/api/forecast/v1/eligibility/override` | 人工纳入/排除（记录操作人、时间、原因） |
| GET | `/api/forecast/v1/eligibility/rules` | 查看准入规则配置 |
| GET | `/api/forecast/v1/eligibility/history` | 资格变化审计记录 |
| POST | `/api/forecast/v1/eligibility/evaluate-all` | 触发全量评估 |

八种状态：`eligible` / `probation` / `cold` / `insufficient_history` / `poor_data_quality` / `low_predictability` / `manually_excluded` / `manually_included`

### 1.3 测试结果

- 全量评估 31 个对象 → **eligible 23 / cold 6 / probation 1**
- 周期性检测有效：核心应用周周期强度 0.70~0.75，冷系统 0.00
- 人工纳入：`cold-archive` 由 `cold` → `manually_included`，记录操作人 `admin`，审计历史可查
- 前端 Docker 编译通过：`✓ 905 modules transformed`，产物 `ForecastObjectsPage-BGqWt0FV.js` 41.60 kB

### 1.4 已知问题

1. `ai_query_embeddings` 表未迁移成功（原库含 pgvector 的 vector 列，新 PG16 未装 pgvector），影响 AI 语义检索的 embedding 缓存；核心监控表与预测功能不受影响
2. 前端筛选为本地筛选（基于 `limit=1000` 全量拉取），对象数超 1000 需切服务端筛选
3. 开发环境前端直连 `localhost:8090` 依赖 CORS；生产建议用 `VITE_FORECAST_API_BASE_URL` 走网关反代

---

## 二、阶段三：常规交易量预测引擎

### 2.1 代码变更清单

| 文件 | 说明 |
|---|---|
| `forecast-service/app/forecast/dataset.py` | 时序加载 + 重采样，**严格区分真实零流量与数据缺失**（需求 §3.3） |
| `forecast-service/app/forecast/models.py` | Seasonal Naive / ETS(Holt-Winters) / SARIMA / LightGBM；预测区间用残差分位数 |
| `forecast-service/app/forecast/backtest.py` | 时间顺序滚动回测（不随机打乱），MAE/WAPE/sMAPE/覆盖率/相对基线改善 |
| `forecast-service/app/forecast/engine.py` | 资格校验 → 模型 auto 选择 → 预测 → 区间 → 存储 |
| `forecast-service/app/storage/forecast_store.py` | 预测结果存储（内存 + PG） |
| `forecast-service/sql/002_forecast.sql` | `forecast_results` 表（JSONB 存曲线/汇总/回测） |
| `forecast-service/app/api/main.py` | 4 个预测接口 |

### 2.2 接口说明

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/forecast/v1/predict` | 创建预测任务（**先验资格**，不合格默认拒绝） |
| GET | `/api/forecast/v1/result/{forecast_id}` | 查询完整预测曲线、模型信息、数据质量、区间 |
| GET | `/api/forecast/v1/evaluation` | 查询滚动回测指标 |
| GET | `/api/forecast/v1/forecasts` | 历史预测记录 |

`predict` 请求体：`app_name` / `uri_template` / `metric` / `granularity`(5m) / `horizon`(24h) / `scenario`(baseline) / `model_strategy`(auto) / `include_interval` / `force`

### 2.3 测试结果（core-payment，24h，5min 粒度）

| 模型 | MAE | WAPE | sMAPE | 区间覆盖率 | 相对基线改善 |
|---|---|---|---|---|---|
| Seasonal Naive（基线） | 377.3 | 0.122 | 0.122 | 0.667 | — |
| **LightGBM（auto 选中）** | **262.2** | **0.085** | **0.086** | 0.616 | **+30.5%** |

- 输出 288 个 5min 点，含 `baseline_forecast` / `lower_bound` / `upper_bound` / `avg_qps`
- ETS 模型单独指定可用（1h 粒度 24 点）
- 冷系统 `cold-archive` 常规预测 → **正确拒绝 HTTP 400** 并返回原因
- `force=true` → 保留风险标识「冷系统：常规基线不可靠，如需预测请走活动专项」

### 2.4 已知问题

1. **`peak_qps` 恒为 null** — 5min 聚合无法得到真实瞬时峰值，符合需求 §6.4 明确要求（不得用平均 QPS 冒充峰值）。需接入更细粒度数据后才能输出
2. **区间覆盖率 0.62 低于 0.9 目标** — 残差分位数法偏窄，后续可用 conformal prediction 或分位数回归校准
3. SARIMA 在 5min 粒度（季节周期 288）下极慢，已做截断与异常回退；建议高频场景优先用 LightGBM
4. `event_increment` / `event_adjusted_forecast` 目前与 baseline 相同，**阶段四（活动影响分析）才会填充**

---

## 三、核心设计原则落实检查

| 原则 | 落实 |
|---|---|
| 算法算数字，LLM 只解释 | ✅ 预测值/区间均来自模型残差分位数，无 LLM 参与 |
| 不得把缺失当零交易 | ✅ `dataset.py` 区分 `is_missing` 与真实零 |
| 冷系统保留监控但不入常规预测 | ✅ 拒绝常规预测，需活动专项或人工强制 |
| 人工强制纳入须标风险 | ✅ `risk_flags` 输出风险标识 |
| Mock 数据须标识、不进生产报告 | ✅ 页面顶部 Mock 横幅 + `data_source=mock` 字段 |
| 不破坏现有监控能力 | ✅ PG 拆分后 8088 返回 200，核心表完整（除 pgvector 表见 1.4.1） |
