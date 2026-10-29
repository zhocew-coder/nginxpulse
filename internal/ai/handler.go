package ai

import (
	"fmt"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/likaia/nginxpulse/internal/store"
)

// Handler handles AI-related HTTP requests
type Handler struct {
	anomalyDetector *AnomalyDetector
	nl2sqlEngine    *NL2SQLEngine
	reportGenerator *ReportGenerator
}

// NewHandler creates a new AI handler
func NewHandler(db *store.Repository, llm *LLMClient) *Handler {
	return &Handler{
		anomalyDetector: NewAnomalyDetector(db, llm),
		nl2sqlEngine:    NewNL2SQLEngine(llm, db),
		reportGenerator: NewReportGenerator(llm, db),
	}
}

// RegisterRoutes registers AI routes
func RegisterRoutes(router *gin.Engine, db *store.Repository, llm *LLMClient) {
	handler := NewHandler(db, llm)

	api := router.Group("/api/ai")
	{
		// Anomaly detection
		api.GET("/anomalies", handler.GetAnomalies)
		api.POST("/anomalies/detect", handler.DetectAnomalies)
		api.GET("/anomalies/:id", handler.GetAnomalyByID)

		// NL2SQL query
		api.POST("/query", handler.Query)

		// Reports
		api.GET("/reports/daily", handler.GetDailyReport)
		api.GET("/reports/weekly", handler.GetWeeklyReport)
		api.GET("/reports/monthly", handler.GetMonthlyReport)
		api.POST("/reports/generate", handler.GenerateReport)
	}
}

// GetAnomalies retrieves anomaly reports
func (h *Handler) GetAnomalies(c *gin.Context) {
	hours := 24
	if h := c.Query("hours"); h != "" {
		if _, err := fmt.Sscanf(h, "%d", &hours); err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": "invalid hours parameter"})
			return
		}
	}

	reports, err := h.anomalyDetector.GetReports(c.Request.Context(), hours)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"reports": reports,
		"count":   len(reports),
	})
}

// DetectAnomalies manually triggers anomaly detection
func (h *Handler) DetectAnomalies(c *gin.Context) {
	// Honour the time window requested by the client instead of always the last hour
	hours := 24
	if v := c.Query("hours"); v != "" {
		if _, err := fmt.Sscanf(v, "%d", &hours); err != nil || hours <= 0 {
			c.JSON(http.StatusBadRequest, gin.H{"error": "invalid hours parameter"})
			return
		}
	}
	if hours > 168 {
		hours = 168
	}
	var req struct {
		Hours int `json:"hours"`
	}
	// Body wins over query string so the frontend's payload is respected
	if err := c.ShouldBindJSON(&req); err == nil && req.Hours > 0 {
		if req.Hours > 168 {
			req.Hours = 168
		}
		hours = req.Hours
	}

	endTime := time.Now()
	startTime := endTime.Add(-time.Duration(hours) * time.Hour)

	reports, err := h.anomalyDetector.DetectByTimeRange(c.Request.Context(), startTime, endTime)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	// Add LLM risk judgement + mitigation plan to each detection
	reports = h.anomalyDetector.EnrichWithLLM(c.Request.Context(), reports)

	llmCount := 0
	for _, r := range reports {
		if r.LLMGenerated {
			llmCount++
		}
	}

	// Build a aggregated summary for heavy_hitter so the frontend can render
	// a single chart instead of one card per IP.
	type hitter struct {
		IP           string     `json:"ip"`
		SharePct     float64    `json:"share_pct"`
		RequestCount int        `json:"request_count"`
		TopURLs      []URLCount `json:"top_urls"`
	}
	hitterSummary := []hitter{}
	for _, r := range reports {
		if r.Type == "heavy_hitter" && len(r.SourceIPs) > 0 {
			hitterSummary = append(hitterSummary, hitter{
				IP:           r.SourceIPs[0],
				SharePct:     r.SharePct,
				RequestCount: r.RequestCount,
				TopURLs:      r.TopURLs,
			})
		}
	}
	totalShare := 0.0
	for _, h := range hitterSummary {
		totalShare += h.SharePct
	}

	// Get a summary-level LLM judgement for all heavy hitters together
	hhSummary := h.anomalyDetector.SummarizeHeavyHitters(c.Request.Context(), reports)

	c.JSON(http.StatusOK, gin.H{
		"reports":              reports,
		"count":                len(reports),
		"hours":                hours,
		"llm_analyzed":         llmCount,
		"heavy_hitters":        hitterSummary,
		"hitter_total_share":   totalShare,
		"hitter_summary":       hhSummary,
		"message":              "anomaly detection completed",
	})
}

// GetAnomalyByID retrieves a specific anomaly report
func (h *Handler) GetAnomalyByID(c *gin.Context) {
	id := c.Param("id")
	// Implementation to fetch by ID
	c.JSON(http.StatusOK, gin.H{"id": id, "message": "not implemented yet"})
}

// Query handles NL2SQL queries
func (h *Handler) Query(c *gin.Context) {
	var req struct {
		Question string `json:"question"`
	}

	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	if req.Question == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "question is required"})
		return
	}

	// Parse question to SQL
	sqlQuery, err := h.nl2sqlEngine.ParseQuestion(c.Request.Context(), req.Question)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	// Execute query
	result, err := h.nl2sqlEngine.Execute(c.Request.Context(), sqlQuery)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	// Turn the raw rows into a business + operations interpretation
	analysis := h.nl2sqlEngine.AnalyzeResult(c.Request.Context(), req.Question, sqlQuery.SQL, result)

	c.JSON(http.StatusOK, gin.H{
		"question": req.Question,
		"sql":      sqlQuery.SQL,
		"results":  result.Rows,
		"count":    result.Count,
		"answer":   analysis.Answer,
		// structured LLM narrative
		"business_insight": analysis.BusinessInsight,
		"ops_advice":       analysis.OpsAdvice,
		"highlights":       analysis.Highlights,
		"risk_alerts":      analysis.RiskAlerts,
		"llm_generated":    analysis.LLMGenerated,
	})
}

// GetDailyReport retrieves a daily report
func (h *Handler) GetDailyReport(c *gin.Context) {
	dateStr := c.Query("date")
	if dateStr == "" {
		dateStr = time.Now().Format("2006-01-02")
	}

	date, err := time.ParseInLocation("2006-01-02", dateStr, time.Local)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid date format, use YYYY-MM-DD"})
		return
	}

	report, err := h.reportGenerator.GenerateDaily(c.Request.Context(), date, false)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	c.JSON(http.StatusOK, report)
}

// GetWeeklyReport retrieves a weekly report
func (h *Handler) GetWeeklyReport(c *gin.Context) {
	weekStr := c.Query("week")
	if weekStr == "" {
		_, week := time.Now().ISOWeek()
		weekStr = fmt.Sprintf("%d-W%d", time.Now().Year(), week)
	}

	// Parse week string (e.g., "2026-W43")
	// Simplified implementation
	c.JSON(http.StatusOK, gin.H{
		"week":    weekStr,
		"message": "not implemented yet",
	})
}

// GetMonthlyReport retrieves a monthly report
func (h *Handler) GetMonthlyReport(c *gin.Context) {
	monthStr := c.Query("month")
	if monthStr == "" {
		monthStr = time.Now().Format("2006-01")
	}

	// Parse month string (e.g., "2026-10")
	// Simplified implementation
	c.JSON(http.StatusOK, gin.H{
		"month":   monthStr,
		"message": "not implemented yet",
	})
}

// GenerateReport manually generates a report
func (h *Handler) GenerateReport(c *gin.Context) {
	var req struct {
		Type    string `json:"type"` // daily, weekly, monthly
		Date    string `json:"date"`
		Refresh bool   `json:"refresh"`
	}

	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	// Use the server's local timezone so "2026-10-28" means local midnight
	date, err := time.ParseInLocation("2006-01-02", req.Date, time.Local)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid date format, use YYYY-MM-DD"})
		return
	}

	var report *Report
	switch req.Type {
	case "daily":
		report, err = h.reportGenerator.GenerateDaily(c.Request.Context(), date, req.Refresh)
	case "weekly":
		report, err = h.reportGenerator.GenerateWeekly(c.Request.Context(), date, req.Refresh)
	case "monthly":
		report, err = h.reportGenerator.GenerateMonthly(c.Request.Context(), date.Year(), date.Month(), req.Refresh)
	default:
		err = fmt.Errorf("invalid report type: %s", req.Type)
	}

	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	c.JSON(http.StatusOK, report)
}
