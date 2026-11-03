-- 预测资格表：应用/URL 层级的预测准入状态
-- 阶段二：预测准入过滤模块
CREATE TABLE IF NOT EXISTS forecast_eligibility (
    id                      BIGSERIAL PRIMARY KEY,
    level                   TEXT NOT NULL,              -- app / uri
    app_name                TEXT NOT NULL,
    uri_template            TEXT NOT NULL DEFAULT '',  -- '' 表示应用级聚合
    total_requests          BIGINT NOT NULL DEFAULT 0,
    active_days             INT NOT NULL DEFAULT 0,
    active_day_ratio        DOUBLE PRECISION NOT NULL DEFAULT 0,
    nonzero_buckets         INT NOT NULL DEFAULT 0,
    nonzero_bucket_ratio    DOUBLE PRECISION NOT NULL DEFAULT 0,
    data_completeness       DOUBLE PRECISION NOT NULL DEFAULT 0,
    avg_daily_requests      DOUBLE PRECISION NOT NULL DEFAULT 0,
    max_daily_requests      BIGINT NOT NULL DEFAULT 0,
    avg_interarrival_minutes DOUBLE PRECISION,
    weekly_seasonality_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    monthly_seasonality_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    history_days            INT NOT NULL DEFAULT 0,
    status                  TEXT NOT NULL,             -- 8 种状态
    predictability          TEXT NOT NULL,             -- high/medium/low/none
    eligibility_score       DOUBLE PRECISION NOT NULL DEFAULT 0,
    reasons                 TEXT[] NOT NULL DEFAULT '{}',
    bucket_count            INT NOT NULL DEFAULT 0,
    missing_buckets         INT NOT NULL DEFAULT 0,
    night_concentration     DOUBLE PRECISION NOT NULL DEFAULT 0,
    -- 人工覆盖
    override_status         TEXT,
    override_reason         TEXT,
    override_by             TEXT,
    override_at             TIMESTAMPTZ,
    -- 活动专项纳入
    event_included          BOOLEAN NOT NULL DEFAULT FALSE,
    event_confidence        TEXT NOT NULL DEFAULT 'not_applicable',
    -- 元信息
    config_version          TEXT NOT NULL DEFAULT 'v1',
    data_source             TEXT NOT NULL DEFAULT 'mock',
    evaluated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (level, app_name, uri_template)
);

CREATE INDEX IF NOT EXISTS idx_eligibility_status ON forecast_eligibility(status);
CREATE INDEX IF NOT EXISTS idx_eligibility_app ON forecast_eligibility(app_name);
CREATE INDEX IF NOT EXISTS idx_eligibility_evaluated_at ON forecast_eligibility(evaluated_at);

-- 资格变化历史（审计）
CREATE TABLE IF NOT EXISTS forecast_eligibility_history (
    id                      BIGSERIAL PRIMARY KEY,
    level                   TEXT NOT NULL,
    app_name                TEXT NOT NULL,
    uri_template            TEXT NOT NULL DEFAULT '',
    old_status              TEXT,
    new_status              TEXT NOT NULL,
    old_score               DOUBLE PRECISION,
    new_score               DOUBLE PRECISION,
    change_type             TEXT NOT NULL,   -- auto / override / event_include
    operator                TEXT,
    reason                  TEXT,
    occurred_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_eligibility_history_obj
    ON forecast_eligibility_history(level, app_name, uri_template);

-- 准入规则配置表（可配置，不硬编码）
CREATE TABLE IF NOT EXISTS forecast_eligibility_rules (
    id                      BIGSERIAL PRIMARY KEY,
    config_version          TEXT NOT NULL UNIQUE,
    lookback_days           INT NOT NULL DEFAULT 56,
    min_history_days_min    INT NOT NULL DEFAULT 14,
    min_history_days_full   INT NOT NULL DEFAULT 28,
    min_completeness        DOUBLE PRECISION NOT NULL DEFAULT 0.95,
    cold_total_requests     INT NOT NULL DEFAULT 100,
    cold_active_days        INT NOT NULL DEFAULT 5,
    probation_total_requests INT NOT NULL DEFAULT 500,
    probation_active_days   INT NOT NULL DEFAULT 20,
    seasonality_acf_threshold DOUBLE PRECISION NOT NULL DEFAULT 0.3,
    batch_concentration_threshold DOUBLE PRECISION NOT NULL DEFAULT 0.6,
    score_weights           JSONB NOT NULL,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
