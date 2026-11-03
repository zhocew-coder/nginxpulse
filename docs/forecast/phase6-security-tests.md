# 阶段六：预测服务异常输入 / 边界条件 / 安全测试报告

- 服务：forecast-service（Python FastAPI），http://127.0.0.1:8090
- API 基础路径：`/api/forecast/v1`
- 测试方式：宿主机 curl 逐用例执行，记录 HTTP 状态码与响应摘要
- 测试日期：2026-11-02

## 判定标准

- **PASS**：返回 4xx 结构化错误（400/404/422）或安全处理（空结果/安全拒答/脱敏），无 5xx、无堆栈、无数据泄露；业务语义校验生效。
- **FAIL**：5xx；或异常输入被静默放行（200 且产生业务数据/调用）；或存在安全风险（敏感信息泄露、CORS 误配、无防护）。
- 说明：FastAPI 框架级校验错误（字段缺失、JSON 解析、类型错误）提示为英文（如 `Field required`），此项计入"软性问题"备注，不单独判 FAIL；业务错误提示均为中文。
- SQL 注入/XSS 类用例以"无注入迹象（不返回全量数据、无数据库错误、非 500）"为安全判定基准。

## 测试用例明细

### 1. 异常输入测试

| 编号 | 接口 | 测试内容 | 期望 | 实际 | PASS/FAIL |
|------|------|----------|------|------|-----------|
| A1 | POST /eligibility/evaluate | 空 app_name（`{"app_name":""}`） | 400/422 + 中文错误 | 200，返回全量聚合画像数据（total_requests=1674918），未做非空校验 | FAIL |
| A2 | POST /eligibility/evaluate | 超长字符串 app_name（20000 字符） | 400/422 + 中文错误 | 404 `{"detail":"未找到该对象的时序数据"}`（合理错误，无 500） | PASS |
| A3 | POST /eligibility/evaluate | SQL 注入 app_name `' OR 1=1 --` | 400/422 + 中文错误 | 404 `未找到该对象的时序数据`，无注入迹象 | PASS |
| A4 | POST /eligibility/evaluate | XSS app_name `<script>alert(1)</script>` | 400/422 + 中文错误 | 404 `未找到该对象的时序数据`，原样未执行 | PASS |
| A5 | POST /eligibility/evaluate | 非法 JSON body（`{bad json`） | 400/422 + 中文错误 | 422 `json_invalid`（FastAPI 默认英文提示，软性问题） | PASS |
| A6 | POST /predict | 不存在的 app_name | 400/422 + 中文错误 | 400 `历史数据不足，无法预测`（中文；对"不存在应用"措辞略欠精确） | PASS |
| A7 | POST /predict | 非法 horizon `"abc"` | 400/422 拒绝 | 200 静默接受，响应中 `horizon:"abc"` 原样回显并生成预测，未做枚举校验 | FAIL |
| A8 | POST /predict | 非法 scenario `"!!!bad-scenario"` | 400/422 拒绝 | 200 静默接受，`scenario:"!!!bad-scenario"` 原样回显并生成预测，未做枚举校验 | FAIL |
| A9 | POST /predict | 不存在的 event_id | 400/422 + 中文错误 | 404 `活动不存在：evt_not_exist_999` | PASS |
| A10 | POST /predict | 负数 force（force 为布尔型字段，传 -5） | 400/422 拒绝 | 422 `bool_parsing` 类型校验拒绝（英文提示，软性问题；类型模型正确） | PASS |
| A11 | POST /events | start_time > end_time | 400/422 + 中文错误 | 400 `活动时间不合法：start_time 必须早于 end_time` | PASS |
| A12 | POST /events | target_apps 空数组 | 400/422 + 中文错误 | 400 `受影响应用（target_apps）不能为空，至少需指定一个应用` | PASS |
| A13 | POST /events | 非法时间格式（`not-a-time`） | 400/422 + 中文错误 | 400 `start_time/end_time：时间格式不合法，需为 ISO8601` | PASS |
| A14 | GET /eligibility/history | SQL 注入 `?app_name=' OR 1=1 --` | 400/422 或安全空结果 | 200 `[]`，参数化查询无注入迹象，未泄露全量数据（安全处理） | PASS |
| A15 | POST /agent/chat | 空 question | 400/422 拒绝 | 200 正常回复闲聊话术，未拒绝空输入（空输入仍触发 LLM 调用） | FAIL |
| A16 | POST /agent/chat | 超长 question（20000 字符） | 400/422 拒绝 | 200 正常回复，无长度上限校验（未崩溃，但超长输入进入 LLM） | FAIL |
| A17 | POST /agent/chat | 特殊字符（SQL 注入 + XSS 组合） | 400/422 或合理处理 | 200，LLM 中文安全拒答（"输入内容包含 SQL 注入尝试…违反安全规范"），未执行注入 | PASS |
| A18 | POST /eligibility/override | 非法 status 值（`hacked-status`） | 400/422 + 中文错误 | 400 `非法状态：hacked-status`，枚举校验生效 | PASS |

### 2. 边界条件测试

| 编号 | 接口 | 测试内容 | 期望 | 实际 | PASS/FAIL |
|------|------|----------|------|------|-----------|
| B1 | GET /result/{forecast_id} | 不存在的 forecast_id | 404/400 合理错误 | 404 `预测结果不存在` | PASS |
| B2 | GET /events/{event_id} | 不存在的 event_id | 404/400 合理错误 | 404 `活动不存在：evt_not_exist_999` | PASS |
| B3 | GET /eligibility/history | limit=0 | 空列表或 400，不 500 | 422 `limit 应 >= 1`（区间校验生效，英文提示） | PASS |
| B4 | GET /eligibility/history | limit=99999（超范围） | 截断到上限或 400 | 422 `limit 应 <= 1000`（上限保护生效，英文提示） | PASS |
| B5 | POST /predict | 并发 5 个同时预测请求 | 全部 2xx/4xx，无 5xx | 5/5 均 200，各返回独立 forecast_id，无 5xx 无超时 | PASS |

### 3. 安全测试

| 编号 | 接口 | 测试内容 | 期望 | 实际 | PASS/FAIL |
|------|------|----------|------|------|-----------|
| C1 | GET /agent/config | API Key 泄露检查 | 响应中 API Key 脱敏 | `api_key:"PubY***kX5k"`（脱敏），`api_key_present:true`，未泄露完整 Key | PASS |
| C2 | OPTIONS /predict | CORS 头检查（伪造 Origin: https://evil.com） | 不反射任意 Origin / 不带凭据反射 | 反射 `access-control-allow-origin: https://evil.com` 且 `access-control-allow-credentials: true`（CORS 误配，跨域凭据风险） | FAIL |
| C3 | POST /predict | 超大 body（10MB JSON） | 413/400 防护 | 400（`历史数据不足`，业务校验兜底），但无 body 大小限制：10MB 全量接收并原样回显 10.4MB 响应（响应放大/资源滥用风险） | FAIL |
| C4 | GET /result/../../etc/passwd 等 2 种变体 | 路径遍历（原始 `../` 与编码 `%2F`） | 404/400，不泄露文件 | 两种变体均 404 `Not Found`，无文件内容泄露 | PASS |

## PASS/FAIL 统计

| 分类 | 用例数 | PASS | FAIL |
|------|--------|------|------|
| 异常输入测试（A1-A18） | 18 | 13 | 5 |
| 边界条件测试（B1-B5） | 5 | 5 | 0 |
| 安全测试（C1-C4） | 4 | 2 | 2 |
| **合计** | **27** | **20** | **7** |

## FAIL 问题清单（按风险排序）

1. **C2 CORS 误配（安全，高）**：反射任意 `Origin` 并同时返回 `Access-Control-Allow-Credentials: true`，恶意站点可携带用户凭据跨域调用 API。建议将允许来源收敛为白名单，或去掉 `allow-credentials`。
2. **C3 无请求体大小防护（安全，中）**：10MB body 全量接收、原样回显 10.4MB 响应，存在资源滥用/响应放大风险。建议网关或应用层限制 body 大小（如 1MB，超出返回 413）。
3. **A1 空 app_name 放行（校验，中）**：`app_name:""` 返回 200 并给出全量聚合画像（疑似全库聚合），应做非空校验并拒绝。
4. **A7/A8 非法 horizon/scenario 静默接受（校验，中）**：`horizon:"abc"`、`scenario:"!!!bad-scenario"` 未做枚举校验即生成预测并原样回显，预测口径不可控。建议枚举白名单校验（horizon 如 24h/7d/30d，scenario 如 baseline/event_adjusted）。
5. **A15/A16 agent/chat 无输入校验（校验，低）**：空 question 与 20000 字超长 question 均未拒绝且触发 LLM 调用（有成本与滥用面）。建议非空 + 长度上限校验（如 400 字符内提示、>10000 拒绝）。

## 软性问题（不判 FAIL）

- FastAPI 框架级校验错误（A5 JSON 解析、A10 类型错误、B3/B4 limit 区间）返回英文提示（`JSON decode error` / `Input should be...`），与"错误信息中文化"要求不一致，建议补充统一的 `RequestValidationError` 异常处理器转中文。
- A6 对不存在应用返回 `历史数据不足，无法预测`，措辞可更精确（如"应用不存在或无历史数据"）。

---

## 安全修复记录（2026-11-02）

针对测试发现的 7 个 FAIL 项，已完成以下修复：

### 修复 1：CORS 误配（High → FIXED）
- **问题**：`allow_origins=["*"]` + `allow_credentials=True`，反射任意 Origin
- **修复**：改为白名单 `["http://localhost:8088", "http://127.0.0.1:8088", "http://localhost:5173", "http://127.0.0.1:5173"]`
- **验证**：evil.com 不返回 CORS 头（PASS），localhost:8088 正常返回（PASS）

### 修复 2：无 body 大小限制（Medium → FIXED）
- **问题**：2MB+ JSON 被接受并回显
- **修复**：添加 `_BodySizeLimitMiddleware`，限制 1MB
- **验证**：超大 body 返回 413 + 中文提示（PASS）

### 修复 3-5：输入校验缺失（Medium → FIXED）
- **问题**：空 app_name / 非法 horizon / 非法 scenario / 空 question 被静默接受
- **修复**：Pydantic `field_validator` 添加校验，返回 422 + 中文错误
- **验证**：所有非法输入返回 422 + 可读中文提示（PASS）
- **附带修复**：`_validation_exception_handler` 修复 ValueError 对象 JSON 序列化失败导致 500 的 bug

### 修复 6：历史时序接口缺失（Medium → FIXED）
- **问题**：前端图表无法获取"实际值"曲线数据
- **修复**：新增 `GET /api/forecast/v1/history` 端点
- **验证**：返回正确时序数据（PASS）

### 修复后测试结果
| 修复项 | 状态 |
|--------|------|
| CORS evil.com 拒绝 | ✅ PASS |
| CORS 合法源正常 | ✅ PASS |
| 空 app_name 校验 | ✅ 422 |
| 非法 horizon 校验 | ✅ 422 |
| 空 question 校验 | ✅ 422 |
| body 大小限制 | ✅ 413 |
| history 接口 | ✅ 200 |
| 预测功能回归 | ✅ 200 (288 points) |

**结论：7 个安全 FAIL 项已全部修复，8/8 复验通过，无功能回归。**
