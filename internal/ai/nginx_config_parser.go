package ai

import (
	"bufio"
	"fmt"
	"os"
	"regexp"
	"strings"
)

// NginxConfigParser parses Nginx configuration files
type NginxConfigParser struct{}

// NginxConfig represents parsed Nginx configuration
type NginxConfig struct {
	Servers    []ServerBlock    `json:"servers"`
	Upstreams  []UpstreamBlock  `json:"upstreams"`
	SSLConfigs []SSLConfig      `json:"ssl_configs"`
	RateLimits []RateLimitConfig `json:"rate_limits"`
	ProxyRules []ProxyRule      `json:"proxy_rules"`
}

// ServerBlock represents a server block
type ServerBlock struct {
	ServerName   string   `json:"server_name"`
	Listen       string   `json:"listen"`
	Root         string   `json:"root"`
	SSL          bool     `json:"ssl_enabled"`
	SSLCert      string   `json:"ssl_cert"`
	SSLKey       string   `json:"ssl_key"`
	ProxyPass    string   `json:"proxy_pass"`
	Locations    []Location `json:"locations"`
	ErrorPages   []string `json:"error_pages"`
	StaticPaths  []string `json:"static_paths"`
}

// Location represents a location block
type Location struct {
	Path      string `json:"path"`
	ProxyPass string `json:"proxy_pass"`
	Root      string `json:"root"`
	Alias     string `json:"alias"`
	Rewrite   string `json:"rewrite"`
}

// UpstreamBlock represents an upstream block
type UpstreamBlock struct {
	Name    string   `json:"name"`
	Servers []string `json:"servers"`
}

// SSLConfig represents SSL configuration
type SSLConfig struct {
	ServerName   string `json:"server_name"`
	Enabled      bool   `json:"enabled"`
	Certificate  string `json:"certificate"`
	Key          string `json:"key"`
	Protocols    string `json:"protocols"`
	Ciphers      string `json:"ciphers"`
	HSTS         bool   `json:"hsts"`
}

// RateLimitConfig represents rate limiting configuration
type RateLimitConfig struct {
	Zone string `json:"zone"`
	Rate string `json:"rate"`
}

// ProxyRule represents a proxy rule
type ProxyRule struct {
	Server      string `json:"server"`
	Location    string `json:"location"`
	ProxyPass   string `json:"proxy_pass"`
	Timeout     string `json:"timeout"`
	Headers     map[string]string `json:"headers"`
}

// SecurityIssue represents a security issue
type SecurityIssue struct {
	Level   string `json:"level"` // "critical", "warning", "info"
	Issue   string `json:"issue"`
	Server  string `json:"server"`
	Suggestion string `json:"suggestion"`
}

// NewNginxConfigParser creates a new Nginx config parser
func NewNginxConfigParser() *NginxConfigParser {
	return &NginxConfigParser{}
}

// Parse parses an Nginx configuration file
func (p *NginxConfigParser) Parse(configPath string) (*NginxConfig, error) {
	file, err := os.Open(configPath)
	if err != nil {
		return nil, fmt.Errorf("failed to open file: %w", err)
	}
	defer file.Close()

	config := &NginxConfig{
		Servers:    make([]ServerBlock, 0),
		Upstreams:  make([]UpstreamBlock, 0),
		SSLConfigs: make([]SSLConfig, 0),
		RateLimits: make([]RateLimitConfig, 0),
		ProxyRules: make([]ProxyRule, 0),
	}

	scanner := bufio.NewScanner(file)
	var currentBlock string
	var blockContent []string
	braceCount := 0

	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())

		// Skip comments and empty lines
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}

		// Detect block start
		if strings.HasSuffix(line, "{") {
			if braceCount == 0 {
				currentBlock = line
				blockContent = []string{line}
			} else {
				blockContent = append(blockContent, line)
			}
			braceCount++
			continue
		}

		// Detect block end
		if line == "}" {
			braceCount--
			blockContent = append(blockContent, line)

			if braceCount == 0 {
				// Process completed block
				p.processBlock(config, currentBlock, blockContent)
				currentBlock = ""
				blockContent = nil
			} else {
				blockContent = append(blockContent, line)
			}
			continue
		}

		// Inside a block
		if braceCount > 0 {
			blockContent = append(blockContent, line)
		}
	}

	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("scan error: %w", err)
	}

	return config, nil
}

// processBlock processes a configuration block
func (p *NginxConfigParser) processBlock(config *NginxConfig, header string, lines []string) {
	if strings.HasPrefix(header, "server {") {
		server := p.parseServerBlock(lines)
		config.Servers = append(config.Servers, server)

		// Extract SSL config
		if server.SSL {
			config.SSLConfigs = append(config.SSLConfigs, SSLConfig{
				ServerName:  server.ServerName,
				Enabled:     true,
				Certificate: server.SSLCert,
				Key:         server.SSLKey,
			})
		}
	}

	if strings.HasPrefix(header, "upstream ") {
		upstream := p.parseUpstreamBlock(header, lines)
		config.Upstreams = append(config.Upstreams, upstream)
	}

	// Extract rate limits from http context
	if strings.Contains(header, "limit_req_zone") {
		rateLimit := p.parseRateLimit(lines)
		config.RateLimits = append(config.RateLimits, rateLimit)
	}
}

// parseServerBlock parses a server block
func (p *NginxConfigParser) parseServerBlock(lines []string) ServerBlock {
	server := ServerBlock{
		Locations:   make([]Location, 0),
		ErrorPages:  make([]string, 0),
		StaticPaths: make([]string, 0),
	}

	serverPattern := regexp.MustCompile(`server_name\s+([^;]+);`)
	listenPattern := regexp.MustCompile(`listen\s+([^;]+);`)
	rootPattern := regexp.MustCompile(`root\s+([^;]+);`)
	sslPattern := regexp.MustCompile(`ssl_certificate\s+([^;]+);`)
	sslKeyPattern := regexp.MustCompile(`ssl_certificate_key\s+([^;]+);`)
	proxyPattern := regexp.MustCompile(`proxy_pass\s+([^;]+);`)
	locationPattern := regexp.MustCompile(`location\s+([^{]+)\{`)

	for _, line := range lines {
		line = strings.TrimSpace(line)

		if matches := serverPattern.FindStringSubmatch(line); len(matches) > 1 {
			server.ServerName = strings.TrimSpace(matches[1])
		}

		if matches := listenPattern.FindStringSubmatch(line); len(matches) > 1 {
			listen := strings.TrimSpace(matches[1])
			server.Listen = listen
			if strings.Contains(listen, "ssl") {
				server.SSL = true
			}
		}

		if matches := rootPattern.FindStringSubmatch(line); len(matches) > 1 {
			server.Root = strings.TrimSpace(matches[1])
			server.StaticPaths = append(server.StaticPaths, server.Root)
		}

		if matches := sslPattern.FindStringSubmatch(line); len(matches) > 1 {
			server.SSLCert = strings.TrimSpace(matches[1])
		}

		if matches := sslKeyPattern.FindStringSubmatch(line); len(matches) > 1 {
			server.SSLKey = strings.TrimSpace(matches[1])
		}

		if matches := proxyPattern.FindStringSubmatch(line); len(matches) > 1 {
			server.ProxyPass = strings.TrimSpace(matches[1])
		}

		// Detect locations (simplified)
		if matches := locationPattern.FindStringSubmatch(line); len(matches) > 1 {
			locPath := strings.TrimSpace(matches[1])
			server.Locations = append(server.Locations, Location{
				Path: locPath,
			})
		}
	}

	return server
}

// parseUpstreamBlock parses an upstream block
func (p *NginxConfigParser) parseUpstreamBlock(header string, lines []string) UpstreamBlock {
	namePattern := regexp.MustCompile(`upstream\s+([^{\s]+)`)
	serverPattern := regexp.MustCompile(`server\s+([^;]+);`)

	upstream := UpstreamBlock{
		Servers: make([]string, 0),
	}

	if matches := namePattern.FindStringSubmatch(header); len(matches) > 1 {
		upstream.Name = strings.TrimSpace(matches[1])
	}

	for _, line := range lines {
		if matches := serverPattern.FindStringSubmatch(line); len(matches) > 1 {
			upstream.Servers = append(upstream.Servers, strings.TrimSpace(matches[1]))
		}
	}

	return upstream
}

// parseRateLimit parses rate limit configuration
func (p *NginxConfigParser) parseRateLimit(lines []string) RateLimitConfig {
	zonePattern := regexp.MustCompile(`limit_req_zone\s+[^=]+zone=([^:]+):([^s]+)s`)
	ratePattern := regexp.MustCompile(`rate=(\d+[km]?[rR]?)`)

	rateLimit := RateLimitConfig{}

	for _, line := range lines {
		if matches := zonePattern.FindStringSubmatch(line); len(matches) > 2 {
			rateLimit.Zone = matches[1]
		}
		if matches := ratePattern.FindStringSubmatch(line); len(matches) > 1 {
			rateLimit.Rate = matches[1]
		}
	}

	return rateLimit
}

// AnalyzeSecurity analyzes security configuration
func (p *NginxConfigParser) AnalyzeSecurity(config *NginxConfig) []SecurityIssue {
	var issues []SecurityIssue

	for _, server := range config.Servers {
		// Check for missing HSTS
		if server.SSL {
			hasHSTS := false
			for _, loc := range server.Locations {
				if strings.Contains(loc.Path, "add_header Strict-Transport-Security") {
					hasHSTS = true
					break
				}
			}
			if !hasHSTS {
				issues = append(issues, SecurityIssue{
					Level:      "warning",
					Issue:      "Missing HSTS header",
					Server:     server.ServerName,
					Suggestion: "Add: add_header Strict-Transport-Security \"max-age=31536000; includeSubDomains\" always;",
				})
			}
		}

		// Check for exposed sensitive paths
		for _, loc := range server.Locations {
			if strings.Contains(loc.Path, ".git") || strings.Contains(loc.Path, ".env") {
				issues = append(issues, SecurityIssue{
					Level:      "critical",
					Issue:      fmt.Sprintf("Sensitive path exposed: %s", loc.Path),
					Server:     server.ServerName,
					Suggestion: "Block access: location ~ /\\. { deny all; }",
				})
			}
		}

		// Check for missing SSL
		if !server.SSL && server.ServerName != "" {
			issues = append(issues, SecurityIssue{
				Level:      "warning",
				Issue:      "SSL not enabled",
				Server:     server.ServerName,
				Suggestion: "Enable SSL with Let's Encrypt or other certificate",
			})
		}
	}

	return issues
}
