# Nginx 交易量预测与 AI 业务态势分析模块 — 部署文档

> 版本：V1.1 · 更新日期：2026-11-02

---

## 1. 系统架构

```
┌─────────────────────────────────────────────────────┐
│                    浏览器（用户）                      │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────┐ │
│  │ 预测对象管理  │  │ 活动日历     │  │ 图表分析页  │ │
│  └──────┬───────┘  └──────┬───────┘  └─────┬──────┘ │
└─────────┼─────────────────┼────────────────┼────────┘
          │ HTTP :8088       │                │
          ▼                 ▼                ▼
┌─────────────────────────────────────────────────────┐
│          nginxpulse 前端（Vite SPA + Go 主服务）       │
│                    容器端口 8088                       │
└─────────────────────────┬───────────────────────────┘
                          │ API 代理 / 浏览器直连 :8090
                          ▼
┌─────────────────────────────────────────────────────┐
│          forecast-service（Python FastAPI）           │
│  ┌─────────┐ ┌──────────┐ ┌────────┐ ┌───────────┐ │
│  │ 资格引擎 │ │ 预测引擎  │ │活动管理│ │ AI Agent  │ │
│  └────┬────┘ └────┬─────┘ └───┬────┘ └─────┬─────┘ │
└───────┼───────────┼───────────┼─────────────┼───────┘
        │           │           │             │
        ▼           ▼           ▼             ▼
┌─────────────────────────────────────────────────────┐
│         PostgreSQL 16 + pgvector（:5432）            │
│  forecast_eligibility / forecast_results / events    │
└─────────────────────────────────────────────────────┘
```

### 组件清单

| 组件 | 技术栈 | 端口 | 说明 |
|------|--------|------|------|
| nginxpulse 主服务 | Go + Vue 3 (Vite) | 8088 (HTTP) / 8089 | 前端 SPA + 日志采集后端 |
| forecast-service | Python 3.13 + FastAPI | 8090 | 交易量预测独立服务 |
| PostgreSQL | postgres:16 + pgvector 0.8.7 | 5432 | 统一数据存储 |

---

## 2. 环境要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Linux (x86_64) |
| Docker | >= 20.10 + docker compose v2 |
| Python | 3.13.x（推荐 conda 环境 `workbuddy`） |
| 内存 | >= 4GB（pandas/numpy 处理 70 天时序数据） |
| 磁盘 | >= 10GB（PG 数据 + Mock 生成数据） |

### Python 依赖（forecast-service/requirements.txt）

```
fastapi>=0.110, uvicorn[standard]>=0.27, pydantic>=2.0
pandas>=2.2, numpy>=2.0
psycopg2-binary>=2.9
statsmodels>=0.14, lightgbm>=4.3, scikit-learn>=1.4
```

---

## 3. 部署步骤

### 3.1 启动数据库与主服务（Docker）

```bash
cd /home/joyce/workspace/nginxpulse

# 构建前端 + Go 主服务镜像
docker compose build nginxpulse

# 启动 PG + 主服务
docker compose up -d

# 验证 PG 就绪
docker exec nginxpulse_pg pg_isready -U nginxpulse -d nginxpulse
```

> **注意**：PG 镜像使用本地固化镜像 `nginxpulse-pg:16-vector`（含 pgvector 扩展）。
> 如需重建：
> ```bash
> docker run -d --name tmp-pg postgres:16
> docker cp postgresql-16-pgvector_0.8.7-1.pgdg13+1_amd64.deb tmp-pg:/tmp/
> docker exec tmp-pg bash -c "apt-get update && dpkg -i /tmp/postgresql-16-pgvector*.deb"
> docker commit tmp-pg nginxpulse-pg:16-vector
> docker rm -f tmp-pg
> ```

### 3.2 初始化数据库表

```bash
# 预测模块建表
docker exec -i nginxpulse_pg psql -U nginxpulse -d nginxpulse \
  < forecast-service/sql/001_eligibility.sql
docker exec -i nginxpulse_pg psql -U nginxpulse -d nginxpulse \
  < forecast-service/sql/002_forecast.sql
docker exec -i nginxpulse_pg psql -U nginxpulse -d nginxpulse \
  < forecast-service/sql/003_events.sql

# AI 模块建表（pgvector）
docker exec -i nginxpulse_pg psql -U nginxpulse -d nginxpulse \
  < scripts/ai_migrate.sql
```

### 3.3 启动预测服务（forecast-service）

```bash
# 使用 conda 环境
~/miniconda3/envs/workbuddy/bin/python -m uvicorn \
  app.api.main:app \
  --host 0.0.0.0 --port 8090 \
  --app-dir /home/joyce/workspace/nginxpulse/forecast-service

# 或使用模块入口
cd /home/joyce/workspace/nginxpulse/forecast-service
~/miniconda3/envs/workbuddy/bin/python -m app.main
```

### 3.4 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `FORECAST_HOST` | `0.0.0.0` | 监听地址 |
| `FORECAST_PORT` | `8090` | 监听端口 |
| `DB_HOST` | `127.0.0.1` | PG 地址（Docker 内改为 `nginxpulse_pg`） |
| `DB_PORT` | `5432` | PG 端口 |
| `DB_NAME` | `nginxpulse` | 数据库名 |
| `DB_USER` | `nginxpulse` | 用户名 |
| `DB_PASSWORD` | `nginxpulse` | 密码 |
| `USE_MOCK` | `true` | Mock 数据模式（生产必须设为 `false`） |
| `MOCK_HISTORY_DAYS` | `70` | Mock 历史天数 |
| `ELIGIBILITY_LOOKBACK_DAYS` | `56` | 准入评估回看天数 |

---

## 4. API 接口总览

基础路径：`http://localhost:8090/api/forecast/v1`

### 4.1 预测资格（阶段二）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/eligibility/evaluate` | 单对象资格评估 |
| POST | `/eligibility/evaluate-all` | 全量批量评估 |
| GET | `/eligibility/list` | 对象列表（支持 status 过滤） |
| POST | `/eligibility/override` | 人工纳入/排除 |
| GET | `/eligibility/rules` | 查看准入规则 |
| GET | `/eligibility/history` | 资格变化记录 |

### 4.2 交易量预测（阶段三）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/predict` | 创建预测（支持 event_id 叠加活动） |
| GET | `/result/{forecast_id}` | 查询预测结果 |
| GET | `/evaluation` | 模型回测指标 |
| GET | `/forecasts` | 预测历史列表 |

### 4.3 活动管理（阶段四）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/events` | 创建活动 |
| GET | `/events` | 活动列表 |
| GET | `/events/{event_id}` | 活动详情 |
| GET | `/events/{event_id}/phase` | 查询指定时间点的活动阶段 |
| POST | `/events/init-mock` | 初始化 Mock 活动 |
| DELETE | `/events/{event_id}` | 删除活动 |

### 4.4 AI Agent（阶段五）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/agent/chat` | 自然语言问答（工具调用闭环） |
| GET | `/agent/tools` | 查看 8 个 Agent 工具 |
| GET | `/agent/config` | 查看 LLM 配置（API Key 脱敏） |
| POST | `/agent/tool/execute` | 直接调用单个工具 |

---

## 5. 前端路由

| 路径 | 页面 |
|------|------|
| `/forecast-objects` | 预测对象管理（准入评估、人工覆盖） |
| `/forecast-events` | 活动日历（月历视图、活动 CRUD） |
| `/forecast-overview` | 交易量预测总览（三曲线 + 预测区间 + 活动阶段） |
| `/event-impact` | 活动影响分析（四维差分 + 三情景对比） |

---

## 6. LLM 配置

配置文件：`configs/ai_config.json`

```json
{
  "llm": {
    "provider": "openai",
    "model": "qwen3.5-397b-a17b",
    "apiKey": "your-api-key",
    "baseUrl": "https://your-llm-endpoint/v1",
    "timeout": 120,
    "maxTokens": 4096,
    "temperature": 0.3
  }
}
```

**安全要求**：
- API Key 不得写入代码仓库
- 日志输出自动脱敏（形如 `PubY***kX5k`）
- `GET /agent/config` 返回的 API Key 已脱敏

---

## 7. Mock 数据说明

⚠️ **Mock 数据仅用于开发测试，不可用于生产报告。**

- 所有 Mock 数据响应携带 `"data_source": "mock"` 标识
- 前端页面显示 Mock 警告横幅
- 生产部署必须设 `USE_MOCK=false` 并接入真实 Nginx 日志

Mock 数据特征：
- 31 个预测对象（core/standard/batch/lowfreq/cold 五类）
- 70 天历史、5 分钟粒度
- 3 个演示活动（双十一营销、月末批量、信贷推广）

---

## 8. 运维监控

### 健康检查

```bash
# 预测服务
curl http://localhost:8090/api/forecast/v1/eligibility/rules

# 数据库
docker exec nginxpulse_pg pg_isready -U nginxpulse

# 前端
curl http://localhost:8088/
```

### 日志

```bash
# 预测服务日志（前台运行时 stdout）
# Docker 日志
docker logs nginxpulse_local --tail 100
docker logs nginxpulse_pg --tail 50
```

### 数据备份

```bash
# PG 全量备份
docker exec nginxpulse_pg pg_dump -U nginxpulse nginxpulse > backup_$(date +%Y%m%d).sql

# 恢复
docker exec -i nginxpulse_pg psql -U nginxpulse nginxpulse < backup_20261102.sql
```

---

## 9. 故障排查

| 现象 | 原因 | 解决 |
|------|------|------|
| 8090 不可达 | forecast-service 未启动 | 重新执行 §3.3 启动命令 |
| predict 返回 500 + NaN | 零基线对象除零 | 已修复（`_clean_nan`），确认代码最新 |
| eligibility/list 返回空 | evaluate-all 未执行 | 先 `POST /eligibility/evaluate-all` |
| 活动增量为 0 | 活动时间与预测窗口不重叠 | 检查 event_id 对应活动时间范围 |
| PG 连接失败 | PG 容器未就绪 | `docker compose up -d db` 等 healthcheck |
| 前端 502 | 后端容器未启动 | `docker compose up -d` |
| pgvector 扩展缺失 | 镜像不含扩展 | 见 §3.1 重建镜像说明 |
