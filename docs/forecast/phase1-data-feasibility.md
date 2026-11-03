# 阶段一：系统与数据检查结果 — 数据可行性评估

> 项目：NginxPulse · 交易量预测与 AI 业务态势分析模块 V1.1
> 检查时间：2026-11-02 · 检查方式：docker compose 实运行库 + 真实 SQL 取证
> 运行容器：`nginxpulse_local`（Up，端口 8088/8089）· 数据库：PostgreSQL（docker volume pgdata）

---

## 一、系统架构与数据流（实测）

- 后端：Go 1.24 + Gin + pgx，入口 `cmd/nginxpulse/main.go`
- 日志解析：`internal/ingest/log_parser_parse_line.go`（字段映射、status_code、request_time、upstream_response_time、pageview_flag）
- 统计口径：`internal/analytics/`（realtime / timeseries / overall / client / session）
- 存储：PostgreSQL，星型模型（原始日志 + 维度表 + 时序聚合表）
- 前端：Vue3/Vite/PrimeVue，页面 `Overview/Daily/Realtime/Logs/AI`

关键文件与证据：

| 模块 | 路径 |
|---|---|
| 日志逐行解析 | `internal/ingest/log_parser_parse_line.go:270`（`pageviewFlag := enrich.ShouldCountAsPageView(statusCode,...)`） |
| 原始日志入库 | `internal/store/repository_insert_pipeline.go` |
| 时序聚合 | `internal/analytics/timeseries_stats.go` |
| demo 生成器 | `internal/worker/demo_generator.go`（`demoPaths` 见 :20-28） |
| demo 开关 | `internal/app/app.go:80`（`go worker.RunDemoGenerator(...)`） |

---

## 二、数据库现状（实测 SQL 结果）

### 表清单（25 张，重点 6 张）

| 表 | 作用 |
|---|---|
| `f002_nginx_logs` | **原始日志分区表**（`f002_nginx_logs_default`） |
| `f002_agg_hourly` | 小时聚合（bucket=unix秒, pv/s2xx/s3xx/s4xx/s5xx/traffic/other） |
| `f002_agg_daily` | 日聚合（day, pv/s2xx...） |
| `f002_dim_url` | URL 维度（id, url） |
| `f002_dim_ip` / `f002_dim_location` / `f002_dim_referer` / `f002_dim_ua` | 维度表 |
| `ai_reports` / `ai_anomaly_reports` | AI 报告表 |

### 原始日志时间范围

```sql
SELECT count(*), min(timestamp), max(timestamp),
       (max(timestamp)-min(timestamp))/86400.0 FROM f002_nginx_logs;
```
结果：**49469 行，跨度 0.1 天（约 3 小时），2026-10-28 11:52 ~ 14:46**

### 聚合表范围

```sql
-- f002_agg_hourly: 4 行, 2026-10-28 11:00~14:00 (span 3h)
-- f002_agg_daily:  1 行, 2026-10-28
```

---

## 三、七个关键问题逐一回答

### Q1. 当前历史交易量数据能覆盖多长时间？
**覆盖极短：约 3 小时（0.1 天）。** 原始日志 min~max 仅 3 小时跨度，聚合表也只到 4 个小时桶 / 1 天。
> 配置 `logRetentionDays: 30`（`nginxpulse_config.dev.json`）说明**保留策略允许 30 天**，但当前库内实际只有约 1 小时数据。远低于需求要求的"至少 8 周、最好 6-12 个月"。

### Q2. 能否获取 5 分钟粒度的历史数据？
**技术可行，但数据不足。**
- 原始日志 `f002_nginx_logs.timestamp` 是**秒级 bigint**，可任意重聚合到 5 分钟桶。
- 现有聚合表只存 **hourly 和 daily** 两档，**没有 5min 桶**。
- 结论：5 分钟粒度**靠原始日志实时聚合可得**（需新写聚合逻辑），不是存储层问题，是"历史太短 + 无 5min 聚合表"的问题。

### Q3. 当前有多少应用及 URL？
**1 个 host（应用）+ 88 个 URL。**
- `SELECT count(DISTINCT host) FROM f002_nginx_logs` → **1**（且为空/localhost，见样本 host 列空白）
- `SELECT count(*) FROM f002_dim_url` → **88**
- URL 流量分布**极度均匀**（1548~1712 次，无长尾）：`/index.html` 1712、`/static/images/logo.png` 1646 … `/favicon.ico` 1548。

### Q4. 哪些应用和 URL 属于冷系统？
**当前数据无真实冷系统（0 个 URL < 100 请求）。**
```sql
SELECT count(*) FROM (SELECT url_id,count(*) c FROM f002_nginx_logs GROUP BY url_id HAVING count(*)<100) t; → 0
```
原因：当前 88 个 URL 全部是 `demo_generator.go:20` 里 `demoPaths` 的固定列表，均匀生成，**不含长尾/低频真实接口**。冷系统识别在真实环境才有意义，mock 阶段需**人为构造**低频/冷 URL 才能验证准入过滤。

### Q5. 是否存在适合识别活动影响的历史流量数据？
**不存在。**
- 数据仅覆盖 2026-10-28 单一日期约 3 小时，**无周/月周期、无双十一/月末等历史事件痕迹**。
- 活动影响识别需要跨年、跨活动的历史对照，当前库完全不具备。
- **结论：活动识别必须依赖 mock 历史数据或真实长周期日志，当前零支撑。**

### Q6. 当前日志字段能否区分成功请求、失败请求和真实业务交易？
**能区分成功/失败，无法区分真实业务交易。**

| 语义 | 字段 | 是否具备 |
|---|---|---|
| 成功请求 | `status_code`（2xx：36902+2505+…） | ✅ 实测 status_code 分布完整（200/201/204/301/302/304/400/401/403/404/500/502/503） |
| 失败请求 | `status_code`（4xx/5xx） | ✅ 同上 |
| 真实业务交易 | **无** | ❌ 全库无 `tx/trade/order/business` 业务字段（已全库扫描确认） |
| 耗时 | `request_time_ms` / `upstream_response_time_ms` | ⚠️ 字段存在但 mock 数据多为 0 |
| PV 口径 | `pageview_flag`（0:25024 / 1:24445） | ✅ |

> **结论：只能预测 HTTP 请求量，不能预测"业务交易笔数"。** 符合需求 3.1 的约束——"有真实业务流水号或可靠交易映射规则时才允许预测实际业务交易笔数"，当前不满足，默认以 `request_count` 为预测指标。

### Q7. 现有数据库是否足以支持预测和回测？
**结构足够，数据量严重不足。**

- ✅ 存储结构：原始日志秒级 + hourly/daily 聚合 + 维度表，星型模型，**足以承载时间序列预测的数据模型**。
- ✅ 可扩展：新增预测相关表（活动日历、资格表、预测结果、回测指标）无障碍。
- ❌ 数据量：仅 3 小时 / 1 天，**无法训练任何带周周期/季节性的模型**（SARIMA、Holt-Winters、LightGBM 都至少需数十天）。
- ❌ 无 5min 聚合桶、无活动数据、无业务交易标识。

---

## 四、Mock 数据结论（重要）

实测确认：当前库数据 = **合成演示数据**，证据链：
1. 行数 `49469` 与真实日志文件 `nginx_access.log`（`wc -l` = 49469）**完全一致**；
2. URL 列表 = `demo_generator.go:20 demoPaths` 固定数组；
3. 流量分布均匀无长尾；
4. `app.go:80` 启用了 `RunDemoGenerator`（每分钟 8-25 条）。

> **这意味着：当前环境本就运行在 mock 之上。** 新需求的"提供 mock 数据确保无真实数据源也能运行/测试/验证"完全成立，且与现状一致。
> ⚠️ 但需**明确标识**：mock 数据不得进入生产报告（需求 §十五 第14条）。

---

## 五、数据可行性评估小结

| 数据要素 | 现状 | 对预测模块的影响 |
|---|---|---|
| 历史时长 | 3 小时 | ❌ 不足训练，需 ≥8 周 |
| 时间粒度 | 秒级原始 + hourly/daily | ⚠️ 5min 需新增聚合 |
| 应用/URL | 1 host / 88 URL | ⚠️ 数量少，需 mock 扩展 |
| 冷系统 | 0（mock 均匀） | ⚠️ 需人为构造低频 URL |
| 活动历史 | 无 | ❌ 需 mock 活动 + 长周期 |
| 成功/失败区分 | ✅ status_code | ✅ 可用 |
| 业务交易笔数 | ❌ 无字段 | ❌ 默认预测 request_count |
| 存储结构 | ✅ 星型可扩展 | ✅ 足以支撑 |

**总体结论：**
1. **基础设施（PostgreSQL 星型模型 + Go/Vue 技术栈）足以承载本需求**，无需更换存储或技术栈。
2. **真实历史数据完全缺失**，当前仅 3 小时演示数据。预测算法、活动建模、冷系统识别、回测**全部需要 Mock 数据驱动**才能开发验证。
3. **预测指标锁定为 `request_count`（HTTP 请求量）**，不承诺业务交易笔数预测。
4. 冷系统、活动影响、回测这些重点能力，**必须在 mock 层构造符合业务语义的历史时序**（含周周期、季节性、活动峰值、低频 URL），否则无法验证真实预测能力（需求禁止"静态页面/mock 流程冒充真实预测"——即 mock 时序必须能真实喂给算法跑出预测曲线，而不是前端写死）。

**对阶段二~六的输入：** Mock 数据层需生成 ≥8 周、5 分钟粒度、多应用多 URL（含冷系统）、含活动峰值与历史活动对照的时间序列；准入过滤、预测、活动分析、回测均基于该序列运行。
