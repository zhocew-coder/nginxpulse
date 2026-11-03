-- 预测结果表（阶段三）
-- 需求 §11.9：预测结果必须保留模型版本、数据范围、活动参数和生成时间
CREATE TABLE IF NOT EXISTS forecast_results (
    forecast_id     TEXT PRIMARY KEY,
    level           TEXT NOT NULL,
    app_name        TEXT NOT NULL,
    uri_template    TEXT NOT NULL DEFAULT '',
    metric          TEXT NOT NULL DEFAULT 'request_count',
    granularity     TEXT NOT NULL DEFAULT '5m',
    horizon         TEXT NOT NULL,
    scenario        TEXT NOT NULL DEFAULT 'baseline',
    model           TEXT NOT NULL,
    model_strategy  TEXT NOT NULL DEFAULT 'auto',
    points          JSONB NOT NULL,
    summary         JSONB,
    quality         JSONB,
    backtest        JSONB,
    eligibility     JSONB,
    risk_flags      TEXT[] NOT NULL DEFAULT '{}',
    data_source     TEXT NOT NULL DEFAULT 'mock',
    history_range   JSONB,
    generated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_forecast_results_obj
    ON forecast_results(level, app_name, uri_template);
CREATE INDEX IF NOT EXISTS idx_forecast_results_generated
    ON forecast_results(generated_at DESC);
