package ai

import (
	"encoding/json"
	"fmt"
	"os"
	"strings"
	"time"
)

// Config holds the AI configuration
type Config struct {
	LLM                LLMConfig            `json:"llm"`
	Embedding          EmbeddingConfig      `json:"embedding"`
	AnomalyDetection   AnomalyConfig        `json:"anomalyDetection"`
	NL2SQL             NL2SQLConfig         `json:"nl2sql"`
	Reports            ReportsConfig        `json:"reports"`
}

// LLMConfig holds LLM configuration
type LLMConfig struct {
	Provider    string  `json:"provider"`
	Model       string  `json:"model"`
	APIKey      string  `json:"apiKey"`
	BaseURL     string  `json:"baseUrl"`
	Timeout     int     `json:"timeout"`
	MaxTokens   int     `json:"maxTokens"`
	Temperature float64 `json:"temperature"`
}

// EmbeddingConfig holds embedding configuration
type EmbeddingConfig struct {
	Model     string `json:"model"`
	Dimension int    `json:"dimension"`
}

// AnomalyConfig holds anomaly detection configuration
type AnomalyConfig struct {
	Enabled            bool   `json:"enabled"`
	CheckInterval      string `json:"checkInterval"`
	QPMThreshold       int    `json:"qpmThreshold"`
	ErrorRateThreshold float64 `json:"errorRateThreshold"`
}

// NL2SQLConfig holds NL2SQL configuration
type NL2SQLConfig struct {
	Enabled     bool `json:"enabled"`
	SafetyCheck bool `json:"safetyCheck"`
	MaxLimit    int  `json:"maxLimit"`
}

// ReportsConfig holds reports configuration
type ReportsConfig struct {
	Daily   ReportScheduleConfig `json:"daily"`
	Weekly  ReportScheduleConfig `json:"weekly"`
	Monthly ReportScheduleConfig `json:"monthly"`
}

// ReportScheduleConfig holds report schedule configuration
type ReportScheduleConfig struct {
	Enabled  bool   `json:"enabled"`
	Schedule string `json:"schedule"`
}

// LoadConfig loads AI configuration from file
func LoadConfig(path string) (*Config, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("failed to read config file: %w", err)
	}

	var config Config
	if err := json.Unmarshal(data, &config); err != nil {
		return nil, fmt.Errorf("failed to unmarshal config: %w", err)
	}

	// Expand environment variables in API key
	if strings.HasPrefix(config.LLM.APIKey, "${") && strings.HasSuffix(config.LLM.APIKey, "}") {
		envVar := config.LLM.APIKey[2 : len(config.LLM.APIKey)-1]
		config.LLM.APIKey = os.Getenv(envVar)
	}

	// Set defaults
	if config.LLM.Timeout == 0 {
		config.LLM.Timeout = 30
	}
	if config.LLM.MaxTokens == 0 {
		config.LLM.MaxTokens = 2048
	}
	if config.LLM.Temperature == 0 {
		config.LLM.Temperature = 0.3
	}
	if config.AnomalyDetection.QPMThreshold == 0 {
		config.AnomalyDetection.QPMThreshold = 100
	}
	if config.NL2SQL.MaxLimit == 0 {
		config.NL2SQL.MaxLimit = 1000
	}

	return &config, nil
}

// GetCheckInterval returns the check interval as time.Duration
func (c *AnomalyConfig) GetCheckInterval() time.Duration {
	if c.CheckInterval == "" {
		return 5 * time.Minute
	}
	d, err := time.ParseDuration(c.CheckInterval)
	if err != nil {
		return 5 * time.Minute
	}
	return d
}
