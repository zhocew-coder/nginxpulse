package ai

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"time"
)

// LLMClient represents an OpenAI-compatible LLM client
type LLMClient struct {
	apiKey      string
	baseURL     string
	model       string
	maxTokens   int
	temperature float64
	timeout     time.Duration
	httpClient  *http.Client
}


// ChatMessage represents a chat message
type ChatMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

// ChatRequest represents an OpenAI chat request
type ChatRequest struct {
	Model       string        `json:"model"`
	Messages    []ChatMessage `json:"messages"`
	MaxTokens   int           `json:"max_tokens,omitempty"`
	Temperature float64       `json:"temperature,omitempty"`
	// ChatTemplateKwargs disables the reasoning ("thinking") phase on
	// reasoning-capable models (Qwen3 etc.). Without it the model spends the
	// whole max_tokens budget on reasoning_content and returns an EMPTY
	// message.content, which makes every downstream JSON parse fail.
	ChatTemplateKwargs map[string]interface{} `json:"chat_template_kwargs,omitempty"`
}

// ChatResponse represents an OpenAI chat response
type ChatResponse struct {
	ID      string `json:"id"`
	Choices []struct {
		Message struct {
			Role string `json:"role"`
			// Content is the actual answer. It is empty when the model only
			// produced a reasoning trace.
			Content string `json:"content"`
			// ReasoningContent carries the thinking trace of reasoning models.
			ReasoningContent string `json:"reasoning_content"`
		} `json:"message"`
		FinishReason string `json:"finish_reason"`
	} `json:"choices"`
	Usage struct {
		PromptTokens     int `json:"prompt_tokens"`
		CompletionTokens int `json:"completion_tokens"`
		TotalTokens      int `json:"total_tokens"`
	} `json:"usage"`
}

// NewLLMClient creates a new LLM client from config
func NewLLMClient(config LLMConfig) *LLMClient {
	if config.BaseURL == "" {
		config.BaseURL = "https://api.openai.com/v1"
	}
	if config.Model == "" {
		config.Model = "gpt-4o-mini"
	}
	if config.MaxTokens == 0 {
		config.MaxTokens = 2048
	}
	if config.Temperature == 0 {
		config.Temperature = 0.3
	}
	if config.Timeout == 0 {
		config.Timeout = 30
	}

	return &LLMClient{
		apiKey:      config.APIKey,
		baseURL:     config.BaseURL,
		model:       config.Model,
		maxTokens:   config.MaxTokens,
		temperature: config.Temperature,
		timeout:     time.Duration(config.Timeout) * time.Second,
		httpClient: &http.Client{
			Timeout: time.Duration(config.Timeout) * time.Second,
		},
	}
}

// Chat sends a chat request and returns the response
func (c *LLMClient) Chat(ctx context.Context, messages []ChatMessage) (string, error) {
	reqBody := ChatRequest{
		Model:       c.model,
		Messages:    messages,
		MaxTokens:   c.maxTokens,
		Temperature: c.temperature,
		// Keep the model in "answer mode". Harmless for non-reasoning models;
		// required for Qwen3-style reasoning models to emit message.content.
		ChatTemplateKwargs: map[string]interface{}{
			"enable_thinking": false,
		},
	}

	reqData, err := json.Marshal(reqBody)
	if err != nil {
		return "", fmt.Errorf("failed to marshal request: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, "POST", c.baseURL+"/chat/completions", bytes.NewReader(reqData))
	if err != nil {
		return "", fmt.Errorf("failed to create request: %w", err)
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+c.apiKey)

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return "", fmt.Errorf("failed to send request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return "", fmt.Errorf("API error: status=%d, body=%s", resp.StatusCode, string(body))
	}

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", fmt.Errorf("failed to read response: %w", err)
	}

	var chatResp ChatResponse
	if err := json.Unmarshal(respBody, &chatResp); err != nil {
		return "", fmt.Errorf("failed to unmarshal response: %w", err)
	}

	if len(chatResp.Choices) == 0 {
		return "", fmt.Errorf("no choices in response")
	}

	choice := chatResp.Choices[0]
	content := choice.Message.Content
	if content != "" {
		return content, nil
	}

	// content is empty: the model burned its whole budget on reasoning and got
	// truncated. Surface a diagnosable error instead of silently falling back.
	reasoning := choice.Message.ReasoningContent
	if reasoning != "" {
		return "", fmt.Errorf(
			"LLM returned empty content (finish_reason=%s, reasoning_tokens=%d, max_tokens=%d); "+
				"the model exhausted its budget on reasoning — increase maxTokens or disable thinking",
			choice.FinishReason, chatResp.Usage.CompletionTokens, c.maxTokens)
	}
	return "", fmt.Errorf("LLM returned empty content (finish_reason=%s)", choice.FinishReason)
}

// LoadLLMConfig loads the LLM configuration from a file
func LoadLLMConfig(path string) (*LLMConfig, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("failed to read config file: %w", err)
	}

	var config LLMConfig
	if err := json.Unmarshal(data, &config); err != nil {
		return nil, fmt.Errorf("failed to unmarshal config: %w", err)
	}

	// Expand environment variables
	if config.APIKey == "" {
		config.APIKey = os.Getenv("OPENAI_API_KEY")
	}

	return &config, nil
}
