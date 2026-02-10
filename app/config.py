import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "")
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    base_url: str = os.getenv("BASE_URL", "http://localhost:8000")
    code_length: int = int(os.getenv("CODE_LENGTH", "7"))
    default_expiry_days: int = int(os.getenv("DEFAULT_EXPIRY_DAYS", "30"))
    redis_default_ttl_seconds: int = int(os.getenv("REDIS_DEFAULT_TTL_SECONDS", "86400"))
    rate_limit_per_minute: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
    flush_interval_seconds: int = int(os.getenv("FLUSH_INTERVAL_SECONDS", "10"))

settings = Settings()