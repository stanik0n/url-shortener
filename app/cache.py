from redis import Redis
from app.config import settings

redis_client = Redis.from_url(settings.redis_url, decode_responses=True)

def cache_key_for_code(code: str) -> str:
    return f"code:{code}"

def rate_limit_key(ip: str, minute_bucket: str) -> str:
    return f"rl:{ip}:{minute_bucket}"

def click_key_for_code(code: str) -> str:
    return f"click:{code}"
