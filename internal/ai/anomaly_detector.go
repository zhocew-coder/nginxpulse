package ai

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"math"
	"time"

	"github.com/lib/pq"
	"github.com/likaia/nginxpulse/internal/store"
)

// AnomalyDetector detects traffic anomalies
type AnomalyDetector struct {
	db  *store.Repository
	llm *LLMClient
}

// URLCount pairs a URL with how many times an IP requested it.
type URLCount struct {
	URL  string `json:"url"`
	Count int   `json:"count"`
}

// AnomalyReport represents an anomaly detection report
type AnomalyReport struct {
	ID           int       `json:"id"`
	Type         string    `json:"type"`     // "cc_attack", "crawler", "scanner"
	Severity     string    `json:"severity"` // "high", "medium", "low"
	SourceIPs    []string  `json:"source_ips"`
	// RequestCount is the total number of requests from the source IP(s).
	RequestCount int       `json:"request_count"`
	// SharePct is the percentage of total traffic this IP accounts for.
	// Used to render a horizontal bar chart for heavy_hitter anomalies.
	SharePct float64 `json:"share_pct,omitempty"`
	// TopURLs lists the most-requested URLs for this IP, with counts.
	// Populated only for heavy_hitter anomalies so the chart can show
	// which resources each IP is hammering.
	TopURLs []URLCount `json:"top_urls,omitempty"`
	TimeRange time.Time `json:"time_range"`
	Evidence     []string  `json:"evidence"`
	CreatedAt    time.Time `json:"created_at"`

	// ---- LLM-generated judgement (not persisted, computed per request) ----
	// Title is a short human-readable summary of the anomaly.
	Title string `json:"title,omitempty"`
	// RiskAnalysis explains what this anomaly actually means and how bad it is.
	RiskAnalysis string `json:"risk_analysis,omitempty"`
	// Impact describes the blast radius: who/what is affected and how.
	Impact string `json:"impact,omitempty"`
	// Actions are concrete mitigation steps, ordered by urgency.
	Actions []string `json:"actions,omitempty"`
	// Confidence is the model's confidence in this judgement (0-1).
	Confidence float64 `json:"confidence,omitempty"`
	// LLMGenerated is false when the model failed and the report is raw data.
	LLMGenerated bool `json:"llm_generated"`
}

// anomalyJudgement is the JSON structure the LLM is asked to produce for one anomaly
type anomalyJudgement struct {
	Index        int      `json:"index"`
	Title        string   `json:"title"`
	RiskAnalysis string   `json:"risk_analysis"`
	Impact       string   `json:"impact"`
	Actions      []string `json:"actions"`
	Confidence   float64  `json:"confidence"`
	Severity     string   `json:"severity"`
}

// heavyHitterSummary is the aggregated summary the LLM produces for a group
// of heavy_hitter IPs, so the UI can show one summary card instead of one
// card per IP.
type heavyHitterSummary struct {
	RiskAnalysis string   `json:"risk_analysis"`
	Impact       string   `json:"impact"`
	Actions      []string `json:"actions"`
	Confidence   float64  `json:"confidence"`
	LLMGenerated bool     `json:"llm_generated"`
}

// NewAnomalyDetector creates a new anomaly detector
func NewAnomalyDetector(db *store.Repository, llm *LLMClient) *AnomalyDetector {
	return &AnomalyDetector{
		db:  db,
		llm: llm,
	}
}

// EnrichWithLLM adds a risk judgement and mitigation plan to each detected
// anomaly. It degrades gracefully: if the model is unavailable the reports are
// returned unchanged with LLMGenerated=false.
func (d *AnomalyDetector) EnrichWithLLM(ctx context.Context, reports []AnomalyReport) []AnomalyReport {
	if d.llm == nil || len(reports) == 0 {
		return reports
	}

	// Only analyse the most significant anomalies to keep latency and token
	// usage bounded; the rest stay as raw detections.
	const maxAnalyse = 6
	targets := reports
	if len(targets) > maxAnalyse {
		targets = targets[:maxAnalyse]
	}

	type item struct {
		Index        int      `json:"index"`
		Type         string   `json:"type"`
		Severity     string   `json:"severity"`
		SourceIPs    []string `json:"source_ips"`
		RequestCount int      `json:"request_count"`
		Evidence     []string `json:"evidence"`
	}
	items := make([]item, 0, len(targets))
	for i, r := range targets {
		items = append(items, item{
			Index:        i,
			Type:         r.Type,
			Severity:     r.Severity,
			SourceIPs:    r.SourceIPs,
			RequestCount: r.RequestCount,
			Evidence:     r.Evidence,
		})
	}
	payload, err := json.MarshalIndent(items, "", "  ")
	if err != nil {
		return reports
	}

	prompt := fmt.Sprintf(`你是一名网络安全与稳定性专家。下面是 Nginx 访问日志异常检测引擎刚刚发现的异常行为（原始检测结果）。

检测结果（JSON 数组）：
%s

请严格按以下 JSON 格式输出（不要输出其他文字，不要用 markdown 代码块包裹）：
{
  "judgements": [
    {
      "index": 0,
      "title": "一句话异常标题，含关键数字，15 字以内",
      "risk_analysis": "风险研判：这是什么行为、依据是什么、危险程度如何，80-160 字",
      "impact": "影响面：对服务可用性、带宽成本、数据安全、真实用户体验的具体影响，50-120 字",
      "actions": ["3-4 条按紧急程度排序的处置动作，要具体到 Nginx 配置指令、iptables/fail2ban 命令、WAF 规则等"],
      "confidence": 0.85,
      "severity": "high 或 medium 或 low（可基于证据修正原判定）"
    }
  ]
}

要求：
1. index 必须与输入数组对应，每一条都要给出
2. 所有判断必须基于给定证据，不要臆测不存在的字段
3. actions 必须是可直接执行的命令或配置片段`, string(payload))

	messages := []ChatMessage{
		{
			Role:    "system",
			Content: "你是网络安全与稳定性专家，擅长研判 Web 异常流量并给出可直接执行的处置方案。你必须且只能输出合法 JSON。",
		},
		{Role: "user", Content: prompt},
	}

	content, err := d.llm.Chat(ctx, messages)
	if err != nil {
		log.Printf("[ai][anomaly] LLM judgement failed, returning raw detections: %v", err)
		return reports
	}

	var parsed struct {
		Judgements []anomalyJudgement `json:"judgements"`
	}
	if err := unmarshalJSONContent(content, &parsed); err != nil {
		log.Printf("[ai][anomaly] failed to parse LLM judgement, returning raw detections: %v", err)
		return reports
	}

	for _, j := range parsed.Judgements {
		if j.Index < 0 || j.Index >= len(targets) {
			continue
		}
		r := &reports[j.Index]
		r.Title = j.Title
		r.RiskAnalysis = j.RiskAnalysis
		r.Impact = j.Impact
		r.Actions = j.Actions
		r.Confidence = j.Confidence
		r.LLMGenerated = true
		if j.Severity == "high" || j.Severity == "medium" || j.Severity == "low" {
			r.Severity = j.Severity
		}
	}

	return reports
}

// SummarizeHeavyHitters takes all heavy_hitter reports in the window and
// produces a single aggregate LLM judgement that covers the group as a
// whole. The per-IP LLM judgements are still kept on each report (so the
// raw evidence stays intact), but the UI only renders this summary card.
func (d *AnomalyDetector) SummarizeHeavyHitters(ctx context.Context, reports []AnomalyReport) heavyHitterSummary {
	hitterReports := make([]AnomalyReport, 0, len(reports))
	for _, r := range reports {
		if r.Type == "heavy_hitter" {
			hitterReports = append(hitterReports, r)
		}
	}
	if len(hitterReports) == 0 {
		return heavyHitterSummary{}
	}

	type ipStat struct {
		IP           string     `json:"ip"`
		SharePct     float64    `json:"share_pct"`
		RequestCount int        `json:"request_count"`
		TopURLs      []URLCount `json:"top_urls"`
	}
	ips := make([]ipStat, 0, len(hitterReports))
	for _, r := range hitterReports {
		ips = append(ips, ipStat{
			IP:           r.SourceIPs[0],
			SharePct:     r.SharePct,
			RequestCount: r.RequestCount,
			TopURLs:      r.TopURLs,
		})
	}
	payload, err := json.MarshalIndent(ips, "", "  ")
	if err != nil {
		return heavyHitterSummary{}
	}

	totalShare := 0.0
	for _, ip := range ips {
		totalShare += ip.SharePct
	}

	prompt := fmt.Sprintf(`你是一名网络安全与稳定性专家。下面是 Nginx 访问日志异常检测引擎在给定时间段内发现的所有「超高占比来源」异常 IP（单 IP 流量占比超过 3%）的汇总数据。

异常 IP 列表（JSON）：
%s

所有异常 IP 合计占总流量的 %.2f%%。

请从「整体视角」给出一份总结式研判，而不是针对单个 IP。严格按以下 JSON 格式输出（不要输出其他文字，不要用 markdown 代码块包裹）：
{
  "risk_analysis": "整体风险研判：这批异常 IP 的整体行为特征（访问模式、是否疑似爬虫/压测/CC）、对业务的真实威胁程度，100-180 字",
  "impact": "影响面：对服务可用性、带宽成本、数据库压力、真实用户体验、安全合规的影响，80-120 字",
  "actions": ["3-4 条整体处置建议，按紧急程度排序，要具体到 Nginx 配置指令、iptables/fail2ban 批量规则、限流策略、WAF 规则等，不要针对单个 IP 一条条列"],
  "confidence": 0.85
}

要求：
1. actions 必须是可直接执行的命令或配置片段
2. 从整体治理角度给建议，不要逐个 IP 罗列处置`, string(payload), totalShare)

	messages := []ChatMessage{
		{
			Role:    "system",
			Content: "你是网络安全与稳定性专家，擅长研判 Web 异常流量并给出可直接执行的处置方案。你必须且只能输出合法 JSON。",
		},
		{Role: "user", Content: prompt},
	}

	content, err := d.llm.Chat(ctx, messages)
	if err != nil {
		log.Printf("[ai][anomaly] heavy-hitter summary failed: %v", err)
		return heavyHitterSummary{LLMGenerated: false}
	}

	var summary heavyHitterSummary
	if err := unmarshalJSONContent(content, &summary); err != nil {
		log.Printf("[ai][anomaly] failed to parse heavy-hitter summary: %v", err)
		return heavyHitterSummary{LLMGenerated: false}
	}
	summary.LLMGenerated = true
	return summary
}

// DetectLastHour detects anomalies in the last hour
func (d *AnomalyDetector) DetectLastHour(ctx context.Context) ([]AnomalyReport, error) {
	endTime := time.Now()
	startTime := endTime.Add(-1 * time.Hour)

	return d.DetectByTimeRange(ctx, startTime, endTime)
}

// Detection thresholds. Kept here so the rules are easy to tune in one place.
const (
	// minWindowRequests is the minimum traffic in the window before any
	// statistical judgement makes sense.
	minWindowRequests = 500
	// minHeavyHitterRequests is the minimum requests for a single IP to be
	// considered a heavy hitter.
	minHeavyHitterRequests = 500
	// heavyHitterSharePct is the share of total traffic a single IP must exceed
	// to be flagged. A real user almost never accounts for >3% of site traffic.
	heavyHitterSharePct = 3.0
	// minErrorBurstRequests is the minimum requests before judging error rate.
	minErrorBurstRequests = 50
	// errorBurstRatePct is the per-IP error rate above which the IP is flagged.
	errorBurstRatePct = 30.0
	// maxPersistedReports bounds how many detections are written to the DB.
	maxPersistedReports = 20
)

// DetectByTimeRange detects anomalies in a time range
func (d *AnomalyDetector) DetectByTimeRange(ctx context.Context, startTime, endTime time.Time) ([]AnomalyReport, error) {
	var reports []AnomalyReport

	// Detect IPs that dominate total traffic (bots / load tests / scraping)
	heavyReports, err := d.detectHeavyHitters(ctx, startTime, endTime)
	if err != nil {
		return nil, fmt.Errorf("failed to detect heavy hitters: %w", err)
	}
	reports = append(reports, heavyReports...)

	// Detect IPs generating a disproportionate amount of errors
	errorReports, err := d.detectErrorBurst(ctx, startTime, endTime)
	if err != nil {
		return nil, fmt.Errorf("failed to detect error bursts: %w", err)
	}
	reports = append(reports, errorReports...)

	// Detect high-frequency IPs (potential CC attack)
	ccReports, err := d.detectHighFrequencyIPs(ctx, startTime, endTime)
	if err != nil {
		return nil, fmt.Errorf("failed to detect CC attacks: %w", err)
	}
	reports = append(reports, ccReports...)

	// Detect scanner behavior
	scannerReports, err := d.detectScanners(ctx, startTime, endTime)
	if err != nil {
		return nil, fmt.Errorf("failed to detect scanners: %w", err)
	}
	reports = append(reports, scannerReports...)

	// Detect crawlers
	crawlerReports, err := d.detectCrawlers(ctx, startTime, endTime)
	if err != nil {
		return nil, fmt.Errorf("failed to detect crawlers: %w", err)
	}
	reports = append(reports, crawlerReports...)

	// Save reports to database (bounded, so repeated manual runs do not flood it)
	for i, report := range reports {
		if i >= maxPersistedReports {
			break
		}
		if err := d.saveReport(ctx, report); err != nil {
			return nil, fmt.Errorf("failed to save report: %w", err)
		}
	}

	return reports, nil
}

// detectHeavyHitters flags IPs whose request volume accounts for a
// disproportionate share of total traffic. Real users rarely exceed a few
// percent of site traffic; a single IP at 5%+ is almost always a bot, a load
// test, or a scraping job. This catches slow-and-steady abuse that the QPM
// based CC rule misses entirely.
func (d *AnomalyDetector) detectHeavyHitters(ctx context.Context, startTime, endTime time.Time) ([]AnomalyReport, error) {
	startSec := startTime.Unix()
	endSec := endTime.Unix()

	var total int64
	if err := d.db.GetDB().QueryRowContext(ctx,
		`SELECT COUNT(*) FROM f002_nginx_logs WHERE timestamp >= $1 AND timestamp < $2`,
		startSec, endSec).Scan(&total); err != nil {
		return nil, fmt.Errorf("query total failed: %w", err)
	}
	if total < minWindowRequests {
		return nil, nil
	}

	query := `
		SELECT
			di.ip,
			COUNT(*) AS request_count,
			COUNT(DISTINCT DATE_TRUNC('minute', to_timestamp(l.timestamp))) AS minute_count
		FROM f002_nginx_logs l
		JOIN f002_dim_ip di ON l.ip_id = di.id
		WHERE l.timestamp >= $1 AND l.timestamp < $2
		GROUP BY di.ip
		HAVING COUNT(*) >= $3
		ORDER BY request_count DESC
		LIMIT 20
	`

	rows, err := d.db.GetDB().QueryContext(ctx, query, startSec, endSec, minHeavyHitterRequests)
	if err != nil {
		return nil, fmt.Errorf("query failed: %w", err)
	}
	defer rows.Close()

	var reports []AnomalyReport
	for rows.Next() {
		var ip string
		var count, minuteCount int
		if err := rows.Scan(&ip, &count, &minuteCount); err != nil {
			return nil, fmt.Errorf("scan failed: %w", err)
		}

		share := float64(count) / float64(total) * 100
		if share < heavyHitterSharePct {
			continue
		}

		qpm := float64(count) / math.Max(1, float64(minuteCount))
		severity := "medium"
		if share >= 20 || qpm >= 500 {
			severity = "high"
		} else if share < heavyHitterSharePct*2 {
			severity = "low"
		}

		reports = append(reports, AnomalyReport{
			Type:         "heavy_hitter",
			Severity:     severity,
			SourceIPs:    []string{ip},
			RequestCount: count,
			SharePct:     share,
			TopURLs:      d.topURLsForIP(ctx, ip, startSec, endSec, count),
			TimeRange:    startTime,
			Evidence: []string{
				fmt.Sprintf("Traffic share: %.2f%%", share),
				fmt.Sprintf("Requests: %d", count),
				fmt.Sprintf("QPM: %.2f", qpm),
				fmt.Sprintf("Active minutes: %d", minuteCount),
			},
			CreatedAt: time.Now(),
		})
	}

	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("rows iteration failed: %w", err)
	}

	return reports, nil
}

// topURLsForIP returns the most-requested URLs for a single IP within the
// window. Used to show what a heavy-hitter IP is actually hitting so the
// chart can explain the behaviour (e.g. scraping a specific endpoint).
func (d *AnomalyDetector) topURLsForIP(ctx context.Context, ip string, startSec, endSec int64, _ int) []URLCount {
	query := `
		SELECT u.url, COUNT(*) AS cnt
		FROM f002_nginx_logs l
		JOIN f002_dim_url u ON l.url_id = u.id
		JOIN f002_dim_ip di ON l.ip_id = di.id
		WHERE di.ip = $1 AND l.timestamp >= $2 AND l.timestamp < $3
		GROUP BY u.url
		ORDER BY cnt DESC
		LIMIT 3
	`
	rows, err := d.db.GetDB().QueryContext(ctx, query, ip, startSec, endSec)
	if err != nil {
		return nil
	}
	defer rows.Close()

	var urls []URLCount
	for rows.Next() {
		var u URLCount
		if err := rows.Scan(&u.URL, &u.Count); err != nil {
			continue
		}
		urls = append(urls, u)
	}
	return urls
}

// detectErrorBurst flags IPs that produce a disproportionate share of 4xx/5xx
// responses — the signature of credential stuffing, path fuzzing, or a broken
// client hammering a dead endpoint.
func (d *AnomalyDetector) detectErrorBurst(ctx context.Context, startTime, endTime time.Time) ([]AnomalyReport, error) {
	startSec := startTime.Unix()
	endSec := endTime.Unix()

	query := `
		SELECT
			di.ip,
			COUNT(*) FILTER (WHERE l.status_code >= 400) AS error_count,
			COUNT(*) AS total_count
		FROM f002_nginx_logs l
		JOIN f002_dim_ip di ON l.ip_id = di.id
		WHERE l.timestamp >= $1 AND l.timestamp < $2
		GROUP BY di.ip
		HAVING COUNT(*) >= $3
			AND (COUNT(*) FILTER (WHERE l.status_code >= 400))::float / COUNT(*) * 100 > $4
		ORDER BY error_count DESC
		LIMIT 20
	`

	rows, err := d.db.GetDB().QueryContext(ctx, query, startSec, endSec, minErrorBurstRequests, errorBurstRatePct)
	if err != nil {
		return nil, fmt.Errorf("query failed: %w", err)
	}
	defer rows.Close()

	var reports []AnomalyReport
	for rows.Next() {
		var ip string
		var errorCount, totalCount int
		if err := rows.Scan(&ip, &errorCount, &totalCount); err != nil {
			return nil, fmt.Errorf("scan failed: %w", err)
		}

		rate := float64(errorCount) / float64(totalCount) * 100
		severity := "medium"
		if rate >= 60 && errorCount >= 500 {
			severity = "high"
		} else if rate < 50 {
			severity = "low"
		}

		reports = append(reports, AnomalyReport{
			Type:         "error_burst",
			Severity:     severity,
			SourceIPs:    []string{ip},
			RequestCount: totalCount,
			TimeRange:    startTime,
			Evidence: []string{
				fmt.Sprintf("Error requests: %d", errorCount),
				fmt.Sprintf("Total requests: %d", totalCount),
				fmt.Sprintf("Error rate: %.2f%%", rate),
			},
			CreatedAt: time.Now(),
		})
	}

	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("rows iteration failed: %w", err)
	}

	return reports, nil
}

// detectHighFrequencyIPs detects IPs with abnormally high request frequency
func (d *AnomalyDetector) detectHighFrequencyIPs(ctx context.Context, startTime, endTime time.Time) ([]AnomalyReport, error) {
	// Query: Get IP request counts in the time range (timestamp is Unix seconds)
	query := `
		SELECT
			di.ip,
			COUNT(*) as request_count,
			COUNT(DISTINCT DATE_TRUNC('minute', to_timestamp(l.timestamp))) as minute_count
		FROM f002_nginx_logs l
		JOIN f002_dim_ip di ON l.ip_id = di.id
		WHERE l.timestamp >= $1 AND l.timestamp < $2
		GROUP BY di.ip
		HAVING COUNT(*) > 100
		ORDER BY request_count DESC
		LIMIT 100
	`

	startSec := startTime.Unix()
	endSec := endTime.Unix()
	rows, err := d.db.GetDB().QueryContext(ctx, query, startSec, endSec)
	if err != nil {
		return nil, fmt.Errorf("query failed: %w", err)
	}
	defer rows.Close()

	var reports []AnomalyReport
	for rows.Next() {
		var ip string
		var count, minuteCount int
		if err := rows.Scan(&ip, &count, &minuteCount); err != nil {
			return nil, fmt.Errorf("scan failed: %w", err)
		}

		// Calculate QPM (Queries Per Minute)
		qpm := float64(count) / math.Max(1, float64(minuteCount))

		// If QPM > 100, consider it as CC attack
		if qpm > 100 {
			severity := "medium"
			if qpm > 500 {
				severity = "high"
			}

			reports = append(reports, AnomalyReport{
				Type:         "cc_attack",
				Severity:     severity,
				SourceIPs:    []string{ip},
				RequestCount: count,
				TimeRange:    startTime,
				Evidence: []string{
					fmt.Sprintf("QPM: %.2f", qpm),
					fmt.Sprintf("Total requests: %d", count),
					fmt.Sprintf("Active minutes: %d", minuteCount),
				},
				CreatedAt: time.Now(),
			})
		}
	}

	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("rows iteration failed: %w", err)
	}

	return reports, nil
}

// detectScanners detects IPs scanning sensitive paths
func (d *AnomalyDetector) detectScanners(ctx context.Context, startTime, endTime time.Time) ([]AnomalyReport, error) {
	// Common scanner paths
	scannerPaths := []string{
		"/admin", "/wp-admin", "/.env", "/.git",
		"/phpinfo.php", "/info.php", "/test.php",
		"/backup", "/db", "/sql",
	}

	var reports []AnomalyReport

	startSec := startTime.Unix()
	endSec := endTime.Unix()

	for _, path := range scannerPaths {
		query := `
			SELECT
				di.ip,
				COUNT(*) as request_count
			FROM f002_nginx_logs l
			JOIN f002_dim_ip di ON l.ip_id = di.id
			WHERE l.timestamp >= $1 AND l.timestamp < $2
				AND l.url_id IN (SELECT id FROM f002_dim_url WHERE url LIKE $3)
			GROUP BY di.ip
			HAVING COUNT(*) > 10
			ORDER BY request_count DESC
			LIMIT 50
		`

		rows, err := d.db.GetDB().QueryContext(ctx, query, startSec, endSec, path+"%")
		if err != nil {
			continue
		}

		for rows.Next() {
			var ip string
			var count int
			if err := rows.Scan(&ip, &count); err != nil {
				rows.Close()
				continue
			}

			reports = append(reports, AnomalyReport{
				Type:         "scanner",
				Severity:     "medium",
				SourceIPs:    []string{ip},
				RequestCount: count,
				TimeRange:    startTime,
				Evidence: []string{
					fmt.Sprintf("Scanning path: %s", path),
					fmt.Sprintf("Attempts: %d", count),
				},
				CreatedAt: time.Now(),
			})
		}
		rows.Close()
	}

	return reports, nil
}

// detectCrawlers detects crawler behavior
func (d *AnomalyDetector) detectCrawlers(ctx context.Context, startTime, endTime time.Time) ([]AnomalyReport, error) {
	startSec := startTime.Unix()
	endSec := endTime.Unix()

	// Use browser field to detect crawlers (common bot browsers)
	query := `
		SELECT
			di.ip,
			u.browser,
			COUNT(*) as request_count
		FROM f002_nginx_logs l
		JOIN f002_dim_ua u ON l.ua_id = u.id
		JOIN f002_dim_ip di ON l.ip_id = di.id
		WHERE l.timestamp >= $1 AND l.timestamp < $2
			AND (LOWER(u.browser) LIKE '%%bot%%'
				OR LOWER(u.browser) LIKE '%%spider%%'
				OR LOWER(u.browser) LIKE '%%crawler%%'
				OR LOWER(u.browser) LIKE '%%googlebot%%'
				OR LOWER(u.browser) LIKE '%%bingbot%%')
		GROUP BY di.ip, u.browser
		HAVING COUNT(*) > 50
		ORDER BY request_count DESC
		LIMIT 50
	`

	rows, err := d.db.GetDB().QueryContext(ctx, query, startSec, endSec)
	if err != nil {
		return nil, fmt.Errorf("query failed: %w", err)
	}
	defer rows.Close()

	var reports []AnomalyReport
	for rows.Next() {
		var ip string
		var browser string
		var count int
		if err := rows.Scan(&ip, &browser, &count); err != nil {
			return nil, fmt.Errorf("scan failed: %w", err)
		}

		reports = append(reports, AnomalyReport{
			Type:         "crawler",
			Severity:     "low",
			SourceIPs:    []string{ip},
			RequestCount: count,
			TimeRange:    startTime,
			Evidence: []string{
				fmt.Sprintf("Browser: %s", browser),
				fmt.Sprintf("Requests: %d", count),
			},
			CreatedAt: time.Now(),
		})
	}

	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("rows iteration failed: %w", err)
	}

	return reports, nil
}

// saveReport saves an anomaly report to the database
func (d *AnomalyDetector) saveReport(ctx context.Context, report AnomalyReport) error {
	query := `
		INSERT INTO ai_anomaly_reports 
		(report_type, severity, source_ips, request_count, time_range_start, time_range_end, evidence, created_at)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
	`

	_, err := d.db.GetDB().ExecContext(ctx, query,
		report.Type,
		report.Severity,
		report.SourceIPs,
		report.RequestCount,
		report.TimeRange,
		report.TimeRange.Add(time.Hour),
		report.Evidence,
		report.CreatedAt,
	)

	return err
}

// GetReports retrieves anomaly reports from the database
func (d *AnomalyDetector) GetReports(ctx context.Context, hours int) ([]AnomalyReport, error) {
	startTime := time.Now().Add(-time.Duration(hours) * time.Hour)

	query := `
		SELECT 
			id, report_type, severity, source_ips, request_count,
			time_range_start, time_range_end, evidence, created_at
		FROM ai_anomaly_reports
		WHERE time_range_start >= $1
		ORDER BY created_at DESC
		LIMIT 100
	`

	rows, err := d.db.GetDB().QueryContext(ctx, query, startTime)
	if err != nil {
		return nil, fmt.Errorf("query failed: %w", err)
	}
	defer rows.Close()

	var reports []AnomalyReport
	for rows.Next() {
		var report AnomalyReport
		var endTime time.Time
		if err := rows.Scan(
			&report.ID,
			&report.Type,
			&report.Severity,
			pq.Array(&report.SourceIPs),
			&report.RequestCount,
			&report.TimeRange,
			&endTime,
			pq.Array(&report.Evidence),
			&report.CreatedAt,
		); err != nil {
			return nil, fmt.Errorf("scan failed: %w", err)
		}
		reports = append(reports, report)
	}

	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("rows iteration failed: %w", err)
	}

	return reports, nil
}
