-- 活动日历 / 业务事件表（需求 §4.2，阶段四）
-- 活动影响分析的数据基础：预热期 / 正式期 / 回落期 三段时间窗
CREATE TABLE IF NOT EXISTS forecast_events (
    id                      BIGSERIAL PRIMARY KEY,
    event_id                TEXT NOT NULL,              -- 活动唯一标识
    event_name              TEXT NOT NULL,              -- 活动名称
    event_type              TEXT NOT NULL,              -- marketing/batch/promotion/launch/holiday
    start_time              TIMESTAMPTZ NOT NULL,       -- 正式期开始
    end_time                TIMESTAMPTZ NOT NULL,       -- 正式期结束
    preheat_start           TIMESTAMPTZ,                -- 预热期开始（可为空）
    preheat_end             TIMESTAMPTZ,                -- 预热期结束（可为空，默认=start_time）
    cooldown_end            TIMESTAMPTZ,                -- 回落期结束（可为空）
    target_apps             TEXT[] NOT NULL DEFAULT '{}',  -- 受影响应用列表
    target_uris             TEXT[] NOT NULL DEFAULT '{}',  -- 受影响 URL 模板（空=应用下全部 URL）
    business_type           TEXT NOT NULL DEFAULT '',   -- 业务类型：支付营销/清算批处理/...
    impact_level            TEXT NOT NULL DEFAULT 'medium', -- low/medium/high
    expected_uplift         DOUBLE PRECISION,           -- 预期增幅（如 1.8=+180%）；**可为空，为空时不得编造**
    historical_event_id     TEXT,                       -- 可参考的历史同期活动
    event_owner             TEXT NOT NULL DEFAULT '',   -- 活动负责人 / 归属团队
    data_source             TEXT NOT NULL DEFAULT 'manual', -- mock/manual/external
    confidence              TEXT NOT NULL DEFAULT 'low',   -- high/medium/low（增幅为空时强制 low）
    status                  TEXT NOT NULL DEFAULT 'draft', -- draft/confirmed/completed/cancelled
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_forecast_events_event_id UNIQUE (event_id),
    CONSTRAINT ck_events_time_order CHECK (start_time < end_time)
);

COMMENT ON COLUMN forecast_events.expected_uplift IS
    '预期增幅，可为空；为空表示未标注，任何计算不得编造增幅，须按数据不足/低置信度处理';

CREATE INDEX IF NOT EXISTS idx_events_status ON forecast_events(status);
CREATE INDEX IF NOT EXISTS idx_events_event_type ON forecast_events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_start_time ON forecast_events(start_time);
CREATE INDEX IF NOT EXISTS idx_events_time_range ON forecast_events(start_time, end_time);
CREATE INDEX IF NOT EXISTS idx_events_target_apps ON forecast_events USING GIN (target_apps);

-- 活动变更审计表（创建/更新/删除留痕）
CREATE TABLE IF NOT EXISTS forecast_events_history (
    id                      BIGSERIAL PRIMARY KEY,
    event_id                TEXT NOT NULL,
    action                  TEXT NOT NULL,              -- create/update/delete
    operator                TEXT,
    snapshot                JSONB,
    occurred_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_events_history_event_id
    ON forecast_events_history(event_id, occurred_at DESC);
