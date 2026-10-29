package ai

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/likaia/nginxpulse/internal/store"
)

// NL2SQLEngine converts natural language to SQL queries
type NL2SQLEngine struct {
	llm     *LLMClient
	db      *store.Repository
	examples []NL2SQLExample
}

// NL2SQLExample represents a few-shot example
type NL2SQLExample struct {
	Question string `json:"question"`
	SQL      string `json:"sql"`
	Desc     string `json:"description"`
}

// SQLQuery represents a generated SQL query
type SQLQuery struct {
	SQL         string        `json:"sql"`
	Params      []interface{} `json:"params"`
	Description string        `json:"description"`
	SafetyLevel string        `json:"safety_level"` // "safe", "review_required"
}

// QueryResult represents query results
type QueryResult struct {
	Columns []string                 `json:"columns"`
	Rows    []map[string]interface{} `json:"rows"`
	Count   int                      `json:"count"`
}

// QueryAnalysis is the LLM-generated interpretation of a query result.
// It deliberately splits the narrative into a business view (traffic value,
// user behaviour, content performance) and an operations view (capacity,
// performance, security, config), so the result is actionable for both roles.
type QueryAnalysis struct {
	// Answer is the direct natural-language answer to the question.
	Answer string `json:"answer"`
	// BusinessInsight interprets the numbers from a business standpoint.
	BusinessInsight string `json:"business_insight"`
	// OpsAdvice lists concrete, executable operations actions.
	OpsAdvice []string `json:"ops_advice"`
	// Highlights are the notable findings worth immediate attention.
	Highlights []string `json:"highlights"`
	// RiskAlerts are the risks the data is hinting at (may be empty).
	RiskAlerts []string `json:"risk_alerts"`
	// LLMGenerated is false when the model failed and a template was used.
	LLMGenerated bool `json:"llm_generated"`
}

// NewNL2SQLEngine creates a new NL2SQL engine
func NewNL2SQLEngine(llm *LLMClient, db *store.Repository) *NL2SQLEngine {
	return &NL2SQLEngine{
		llm: llm,
		db:  db,
		examples: []NL2SQLExample{
			{
				Question: "昨天有多少 PV？",
				SQL:      "SELECT COUNT(*) FROM f002_nginx_logs WHERE pageview_flag=1 AND timestamp >= $1 AND timestamp < $2",
				Desc:     "Count PVs in a date range (yesterday)",
			},
			{
				Question: "今天有多少 PV？",
				SQL:      "SELECT COUNT(*) FROM f002_nginx_logs WHERE pageview_flag=1 AND timestamp >= $1 AND timestamp < $2",
				Desc:     "Count PVs today",
			},
			{
				Question: "Top 10 访问路径",
				SQL:      "SELECT u.url, COUNT(*) as cnt FROM f002_nginx_logs l JOIN f002_dim_url u ON l.url_id=u.id GROUP BY u.url ORDER BY cnt DESC LIMIT 10",
				Desc:     "Top 10 paths by request count",
			},
			{
				Question: "今天有多少独立 IP？",
				SQL:      "SELECT COUNT(DISTINCT ip_id) FROM f002_nginx_logs WHERE timestamp >= $1 AND timestamp < $2",
				Desc:     "Count distinct IPs today",
			},
			{
				Question: "错误请求有哪些？",
				SQL:      "SELECT u.url, l.status_code, l.ip_id, l.timestamp FROM f002_nginx_logs l JOIN f002_dim_url u ON l.url_id=u.id WHERE l.status_code >= 400 ORDER BY l.timestamp DESC LIMIT 100",
				Desc:     "Get error requests",
			},
			{
				Question: "平均响应时间是多少？",
				SQL:      "SELECT AVG(request_time_ms) FROM f002_nginx_logs WHERE timestamp >= $1 AND timestamp < $2",
				Desc:     "Average response time today",
			},
		},
	}
}

// ParseQuestion converts a natural language question to SQL
func (e *NL2SQLEngine) ParseQuestion(ctx context.Context, question string) (*SQLQuery, error) {
	// Build few-shot prompt
	var promptBuilder strings.Builder
	promptBuilder.WriteString("你是一名 SQL 专家，负责将自然语言问题转换为 PostgreSQL 查询语句。\n\n")
	promptBuilder.WriteString("可用的表结构：\n")
	promptBuilder.WriteString("- f002_nginx_logs: id, ip_id, pageview_flag, timestamp, method, url_id, status_code, bytes_sent, request_length, request_time_ms\n")
	promptBuilder.WriteString("\n【极其重要的约束】\n")
	promptBuilder.WriteString("1. timestamp 列的类型是 BIGINT，存储的是 Unix 秒级时间戳（例如 1793159548），不是 timestamptz。\n")
	promptBuilder.WriteString("2. 时间范围过滤必须写成裸整数比较，例如：timestamp >= $1 AND timestamp < $2\n")
	promptBuilder.WriteString("3. 绝对禁止写 to_timestamp($1)、$1::timestamptz 或任何把占位符转成时间类型的写法，会导致类型不匹配报错。\n")
	promptBuilder.WriteString("4. 只有在需要对时间做分组（如按小时统计）时才可用 to_timestamp(timestamp) 转换列本身。\n")
	promptBuilder.WriteString("- f002_dim_ip: id, ip\n")
	promptBuilder.WriteString("- f002_dim_url: id, url\n")
	promptBuilder.WriteString("- f002_dim_ua: id, user_agent\n")
	promptBuilder.WriteString("- f002_dim_referer: id, referer\n")
	promptBuilder.WriteString("- websites: id, name, domain, created_at\n\n")
	promptBuilder.WriteString("示例：\n")

	for i, example := range e.examples {
		promptBuilder.WriteString(fmt.Sprintf("%d. 问题：%s\n", i+1, example.Question))
		promptBuilder.WriteString(fmt.Sprintf("   SQL: %s\n\n", example.SQL))
	}

	promptBuilder.WriteString(fmt.Sprintf("现在请将以下问题转换为 SQL：\n问题：%s\nSQL:", question))

	messages := []ChatMessage{
		{
			Role:    "system",
			Content: "你是一名 SQL 专家，只输出 SQL 语句，不要解释。",
		},
		{
			Role:    "user",
			Content: promptBuilder.String(),
		},
	}

	response, err := e.llm.Chat(ctx, messages)
	if err != nil {
		return nil, fmt.Errorf("LLM chat failed: %w", err)
	}

	// Extract SQL from response
	sql := e.extractSQL(response)

	// Safety check
	safetyLevel, err := e.safetyCheck(sql)
	if err != nil {
		return nil, fmt.Errorf("safety check failed: %w", err)
	}

	return &SQLQuery{
		SQL:         sql,
		Params:      e.extractParams(question),
		Description: response,
		SafetyLevel: safetyLevel,
	}, nil
}

// extractSQL extracts SQL statement from LLM response
func (e *NL2SQLEngine) extractSQL(response string) string {
	// Remove markdown code blocks
	response = strings.TrimSpace(response)
	response = regexp.MustCompile("(?s)```sql\\s*(.*?)\\s*```").ReplaceAllString(response, "$1")
	response = regexp.MustCompile("(?s)```\\s*(.*?)\\s*```").ReplaceAllString(response, "$1")

	// Take only the SQL statement (first line if multiple lines)
	lines := strings.Split(response, "\n")
	for _, line := range lines {
		line = strings.TrimSpace(line)
		if line != "" && !strings.HasPrefix(line, "--") {
			return line
		}
	}

	return response
}

// safetyCheck validates the SQL query for security
func (e *NL2SQLEngine) safetyCheck(sql string) (string, error) {
	sql = strings.ToUpper(strings.TrimSpace(sql))

	// Check for dangerous operations
	dangerous := []string{
		"INSERT", "UPDATE", "DELETE", "DROP", "CREATE",
		"ALTER", "TRUNCATE", "GRANT", "REVOKE",
	}

	for _, keyword := range dangerous {
		if strings.Contains(sql, keyword) {
			return "dangerous", fmt.Errorf("dangerous keyword detected: %s", keyword)
		}
	}

	// Check for subquery depth
	subqueryDepth := strings.Count(sql, "SELECT") - 1
	if subqueryDepth > 3 {
		return "dangerous", fmt.Errorf("subquery depth exceeds limit: %d", subqueryDepth)
	}

	// Check for system table access
	if strings.Contains(sql, "PG_") || strings.Contains(sql, "pg_") {
		return "review_required", nil
	}

	// Check for LIMIT
	if !strings.Contains(sql, "LIMIT") {
		return "review_required", nil
	}

	return "safe", nil
}

// relativeDurationRe matches "过去/最近/近 N 小时|天"
var relativeDurationRe = regexp.MustCompile(`(?:过去|最近|近)\s*(\d+)\s*(小时|天|日)`)

// placeholderRe matches SQL placeholders such as $1, $2
var placeholderRe = regexp.MustCompile(`\$(\d+)`)

// alignParams guarantees the parameter count matches the SQL placeholders.
// The LLM frequently emits SQL with time placeholders that extractParams did
// not recognise, which otherwise fails with "expected N arguments, got M".
func alignParams(sql string, params []interface{}) []interface{} {
	maxIdx := 0
	for _, m := range placeholderRe.FindAllStringSubmatch(sql, -1) {
		if n, err := strconv.Atoi(m[1]); err == nil && n > maxIdx {
			maxIdx = n
		}
	}
	if maxIdx == 0 {
		return nil
	}
	if len(params) >= maxIdx {
		return params[:maxIdx]
	}

	// Pad the missing placeholders with a sensible default window (last 24h).
	end := time.Now()
	start := end.Add(-24 * time.Hour)
	out := make([]interface{}, 0, maxIdx)
	out = append(out, params...)
	for len(out) < maxIdx {
		if len(out)%2 == 0 {
			out = append(out, start.Unix())
		} else {
			out = append(out, end.Unix())
		}
	}
	log.Printf("[ai][query] padded SQL params: need %d, got %d (defaulting to last 24h)", maxIdx, len(params))
	return out
}

// extractParams extracts parameters from the question
func (e *NL2SQLEngine) extractParams(question string) []interface{} {
	var params []interface{}

	// Relative duration: "过去 24 小时", "最近 7 天", ...
	if m := relativeDurationRe.FindStringSubmatch(question); m != nil {
		n, err := strconv.Atoi(m[1])
		if err != nil || n <= 0 {
			n = 24
		}
		end := time.Now()
		start := end
		switch m[2] {
		case "小时":
			start = end.Add(-time.Duration(n) * time.Hour)
		default: // 天 / 日
			start = end.AddDate(0, 0, -n)
		}
		return []interface{}{start.Unix(), end.Unix()}
	}

	// Relative week: "过去一周", "最近一周"
	if strings.Contains(question, "过去一周") || strings.Contains(question, "最近一周") ||
		strings.Contains(question, "近一周") || strings.Contains(question, "过去 7 天") {
		end := time.Now()
		return []interface{}{end.AddDate(0, 0, -7).Unix(), end.Unix()}
	}

	// Handle date/time references - timestamp column stores Unix seconds
	if strings.Contains(question, "今天") || strings.Contains(question, "今日") {
		now := time.Now()
		startOfDay := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, now.Location())
		endOfDay := startOfDay.AddDate(0, 0, 1)
		params = append(params, startOfDay.Unix(), endOfDay.Unix())
	}

	if strings.Contains(question, "昨天") || strings.Contains(question, "昨日") {
		yesterday := time.Now().AddDate(0, 0, -1)
		startOfYesterday := time.Date(yesterday.Year(), yesterday.Month(), yesterday.Day(), 0, 0, 0, 0, yesterday.Location())
		endOfYesterday := startOfYesterday.AddDate(0, 0, 1)
		params = append(params, startOfYesterday.Unix(), endOfYesterday.Unix())
	}

	if strings.Contains(question, "本周") || strings.Contains(question, "这周") {
		// Simple implementation
		now := time.Now()
		startOfWeek := time.Date(now.Year(), now.Month(), now.Day()-int(now.Weekday()), 0, 0, 0, 0, now.Location())
		params = append(params, startOfWeek.Unix(), now.Unix())
	}

	if strings.Contains(question, "上周") {
		now := time.Now()
		startOfLastWeek := time.Date(now.Year(), now.Month(), now.Day()-int(now.Weekday())-7, 0, 0, 0, 0, now.Location())
		endOfLastWeek := startOfLastWeek.AddDate(0, 0, 7)
		params = append(params, startOfLastWeek.Unix(), endOfLastWeek.Unix())
	}

	return params
}

// timestampFuncRe matches to_timestamp($1) and to_timestamp($1/1000).
// The timestamp column is a plain BIGINT of Unix seconds, so wrapping the
// placeholder in to_timestamp() produces a timestamptz that cannot be compared
// to the column ("operator does not exist: bigint >= timestamp with time zone").
// LLMs emit this form often enough that it must be normalised defensively.
var timestampFuncRe = regexp.MustCompile(`(?i)to_timestamp\s*\(\s*\$(\d+)\s*(?:/\s*1000(?:\.0)?\s*)?\)`)

// normalizeTimestampExprs rewrites to_timestamp($N) back to $N so the
// placeholder stays a Unix-seconds integer matching the column type.
// Column references such as to_timestamp(timestamp) are deliberately untouched.
func normalizeTimestampExprs(sql string) string {
	return timestampFuncRe.ReplaceAllStringFunc(sql, func(m string) string {
		sub := timestampFuncRe.FindStringSubmatch(m)
		if len(sub) < 2 {
			return m
		}
		return "$" + sub[1]
	})
}

// Execute executes a SQL query and returns results
func (e *NL2SQLEngine) Execute(ctx context.Context, query *SQLQuery) (*QueryResult, error) {
	if query.SafetyLevel == "dangerous" {
		return nil, fmt.Errorf("query marked as dangerous")
	}

	sql := normalizeTimestampExprs(query.SQL)
	if sql != query.SQL {
		log.Printf("[ai][query] normalized timestamp expression in SQL: %q -> %q", query.SQL, sql)
	}

	args := alignParams(sql, query.Params)

	rows, err := e.db.GetDB().QueryContext(ctx, sql, args...)
	if err != nil {
		return nil, fmt.Errorf("query execution failed: %w", err)
	}
	defer rows.Close()

	columns, err := rows.Columns()
	if err != nil {
		return nil, fmt.Errorf("failed to get columns: %w", err)
	}

	result := &QueryResult{
		Columns: columns,
		Rows:    make([]map[string]interface{}, 0),
	}

	values := make([]interface{}, len(columns))
	valuePtrs := make([]interface{}, len(columns))
	for i := range values {
		valuePtrs[i] = &values[i]
	}

	for rows.Next() {
		if err := rows.Scan(valuePtrs...); err != nil {
			return nil, fmt.Errorf("scan failed: %w", err)
		}

		row := make(map[string]interface{})
		for i, col := range columns {
			val := values[i]
			if b, ok := val.([]byte); ok {
				row[col] = string(b)
			} else {
				row[col] = val
			}
		}
		result.Rows = append(result.Rows, row)
		result.Count++

		// Limit results to 1000
		if result.Count >= 1000 {
			break
		}
	}

	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("rows iteration failed: %w", err)
	}

	return result, nil
}

// AnalyzeResult asks the LLM to turn raw query rows into a business + ops
// interpretation. It never fails hard: on any error it degrades to the
// template-based answer so the query itself still returns a usable result.
func (e *NL2SQLEngine) AnalyzeResult(ctx context.Context, question, sql string, result *QueryResult) *QueryAnalysis {
	fallback := &QueryAnalysis{
		Answer:       e.FormatAnswer(question, result),
		LLMGenerated: false,
	}

	if e.llm == nil {
		return fallback
	}

	// Cap the payload: only the first 50 rows are sent to the model.
	sample := result.Rows
	if len(sample) > 50 {
		sample = sample[:50]
	}
	payload, err := json.Marshal(map[string]interface{}{
		"columns":    result.Columns,
		"rows":       sample,
		"row_count":  result.Count,
		"truncated":  len(result.Rows) > len(sample),
		"question":   question,
		"sql":        sql,
		"analyzed_at": time.Now().Format("2006-01-02 15:04:05"),
	})
	if err != nil {
		return fallback
	}

	prompt := fmt.Sprintf(`你是一名兼具业务分析能力的资深 SRE。下面是用户提出的访问数据问题、实际执行的 SQL 以及查询返回的真实结果。

用户问题：%s
执行 SQL：%s
查询结果（JSON）：
%s

请严格按以下 JSON 格式输出（不要输出其他文字，不要用 markdown 代码块包裹）：
{
  "answer": "直接回答用户的问题，1-2 句话，必须引用结果中的真实数字",
  "business_insight": "从业务视角解读：流量规模与质量、访客行为特征、内容/页面的表现差异、对转化或用户体验的影响。120-220 字。",
  "ops_advice": ["3-5 条具体可执行的运维建议，涉及性能、容量、缓存、安全、Nginx 配置、监控告警等，每条要能直接落地"],
  "highlights": ["2-4 条数据中的关键发现，每条一句话并带数字"],
  "risk_alerts": ["1-3 条基于数据推断出的风险提示；如无明显风险则填 []"]
}

要求：
1. 所有结论必须严格基于上面给出的真实数据，禁止编造数字
2. 如果结果为空或为 0，要如实说明，并从运维角度给出排查方向
3. 语言专业简洁，面向技术与业务负责人汇报的场景`, question, sql, string(payload))

	messages := []ChatMessage{
		{
			Role:    "system",
			Content: "你是资深 SRE 兼业务分析师，擅长从访问日志数据中同时提炼业务价值与运维动作。你必须且只能输出合法 JSON。",
		},
		{Role: "user", Content: prompt},
	}

	content, err := e.llm.Chat(ctx, messages)
	if err != nil {
		log.Printf("[ai][query] LLM analysis failed, using template fallback: %v", err)
		return fallback
	}

	var analysis QueryAnalysis
	if err := unmarshalJSONContent(content, &analysis); err != nil {
		log.Printf("[ai][query] failed to parse LLM analysis, using template fallback: %v", err)
		return fallback
	}

	// Keep the direct answer even if the model left it blank.
	if strings.TrimSpace(analysis.Answer) == "" {
		analysis.Answer = fallback.Answer
	}
	analysis.LLMGenerated = true
	return &analysis
}

// unmarshalJSONContent extracts the first JSON object from an LLM response,
// tolerating markdown fences and surrounding prose.
func unmarshalJSONContent(content string, target interface{}) error {
	s := strings.TrimSpace(content)
	if idx := strings.Index(s, "```"); idx >= 0 {
		s = s[idx:]
		s = strings.Replace(s, "```json", "", 1)
		s = strings.Replace(s, "```", "", 1)
		s = strings.TrimSpace(s)
	}
	start := strings.Index(s, "{")
	end := strings.LastIndex(s, "}")
	if start < 0 || end < start {
		return fmt.Errorf("no JSON object found in LLM response")
	}
	return json.Unmarshal([]byte(s[start:end+1]), target)
}

// FormatAnswer formats query results into a natural language answer
func (e *NL2SQLEngine) FormatAnswer(question string, result *QueryResult) string {
	if result.Count == 0 {
		return "未找到相关数据。"
	}

	// Simple formatting based on result structure
	if len(result.Columns) == 1 && result.Count == 1 {
		// Single value result
		val := result.Rows[0][result.Columns[0]]
		return fmt.Sprintf("查询结果：%v", val)
	}

	// Table result
	var sb strings.Builder
	sb.WriteString(fmt.Sprintf("共找到 %d 条记录：\n", result.Count))

	for i, row := range result.Rows {
		if i >= 10 {
			sb.WriteString(fmt.Sprintf("... 还有 %d 条记录", result.Count-10))
			break
		}
		sb.WriteString(fmt.Sprintf("%d. ", i+1))
		for j, col := range result.Columns {
			if j > 0 {
				sb.WriteString(", ")
			}
			sb.WriteString(fmt.Sprintf("%s: %v", col, row[col]))
		}
		sb.WriteString("\n")
	}

	return sb.String()
}
