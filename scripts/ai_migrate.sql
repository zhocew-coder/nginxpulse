-- AI 功能数据库迁移脚本
-- 执行：psql -U nginxpulse -d nginxpulse -f scripts/ai_migrate.sql

-- 启用 pgvector 扩展
CREATE EXTENSION IF NOT EXISTS vector;

-- 异常检测报告表
CREATE TABLE IF NOT EXISTS ai_anomaly_reports (
    id SERIAL PRIMARY KEY,
    report_type VARCHAR(50) NOT NULL,
    severity VARCHAR(20) NOT NULL,
    source_ips TEXT[],
    request_count INTEGER,
    time_range_start TIMESTAMPTZ,
    time_range_end TIMESTAMPTZ,
    evidence TEXT[],
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_anomaly_time ON ai_anomaly_reports(time_range_start);
CREATE INDEX idx_anomaly_type ON ai_anomaly_reports(report_type);
CREATE INDEX idx_anomaly_created ON ai_anomaly_reports(created_at);

-- AI 查询历史表
CREATE TABLE IF NOT EXISTS ai_query_history (
    id SERIAL PRIMARY KEY,
    question TEXT NOT NULL,
    generated_sql TEXT,
    execution_success BOOLEAN,
    result_count INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    user_id VARCHAR(100)
);

CREATE INDEX idx_query_history_created ON ai_query_history(created_at);

-- 报表历史表
CREATE TABLE IF NOT EXISTS ai_reports (
    id SERIAL PRIMARY KEY,
    report_type VARCHAR(20) NOT NULL, -- daily, weekly, monthly
    report_date DATE NOT NULL,
    metrics JSONB,
    insights TEXT[],
    predictions JSONB,
    summary TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_reports_date ON ai_reports(report_type, report_date);
CREATE INDEX idx_reports_created ON ai_reports(created_at);

-- 查询嵌入表（用于语义搜索）
CREATE TABLE IF NOT EXISTS ai_query_embeddings (
    id SERIAL PRIMARY KEY,
    query_text TEXT NOT NULL,
    embedding vector(1536),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_query_embedding ON ai_query_embeddings USING ivfflat (embedding vector_cosine_ops);

-- 插入示例数据（可选）
-- INSERT INTO ai_anomaly_reports (report_type, severity, source_ips, request_count, time_range_start, time_range_end, evidence)
-- VALUES 
-- ('cc_attack', 'high', ARRAY['192.168.1.100'], 5000, NOW() - INTERVAL '1 hour', NOW(), ARRAY['QPM: 500', 'Total requests: 5000']),
-- ('scanner', 'medium', ARRAY['192.168.1.101'], 150, NOW() - INTERVAL '2 hour', NOW(), ARRAY['Scanning path: /admin', 'Attempts: 150']);
