"""预测服务配置。

所有可调参数集中于此，便于测试与生产切换。Mock 相关开关默认开启，
确保无真实数据源时功能可运行、可测试、可验证。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    # 服务
    service_name: str = "nginxpulse-forecast"
    host: str = os.getenv("FORECAST_HOST", "0.0.0.0")
    port: int = int(os.getenv("FORECAST_PORT", "8090"))

    # 数据库（复用 NginxPulse PostgreSQL）
    db_host: str = os.getenv("DB_HOST", "127.0.0.1")
    db_port: int = int(os.getenv("DB_PORT", "5432"))
    db_user: str = os.getenv("DB_USER", "nginxpulse")
    db_password: str = os.getenv("DB_PASSWORD", "nginxpulse")
    db_name: str = os.getenv("DB_NAME", "nginxpulse")

    # Mock 数据源
    # 当 USE_MOCK=true 时，历史时序由 mock 生成器产出，而非真实数据库
    use_mock: bool = _bool("USE_MOCK", True)
    # Mock 历史覆盖天数（建议 ≥8 周 = 56 天）
    mock_history_days: int = int(os.getenv("MOCK_HISTORY_DAYS", "70"))
    # Mock 时间粒度（分钟）：5 表示 5 分钟桶
    mock_bucket_minutes: int = int(os.getenv("MOCK_BUCKET_MINUTES", "5"))
    # Mock 数据种子，保证可复现
    mock_seed: int = int(os.getenv("MOCK_SEED", "20261102"))

    # 准入评估
    # 默认观察窗口（天）
    eligibility_lookback_days: int = int(os.getenv("ELIGIBILITY_LOOKBACK_DAYS", "56"))
    # 准入规则版本（配置变更时递增）
    eligibility_rules_version: str = os.getenv("ELIGIBILITY_RULES_VERSION", "v1")

    @property
    def dsn(self) -> str:
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


settings = Settings()
