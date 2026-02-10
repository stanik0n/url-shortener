from __future__ import annotations

import secrets
import string
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.models import UrlMap
from app.cache import (
    redis_client,
    cache_key_for_code,
    click_key_for_code,
    rate_limit_key,
)

# Base62: A-Z a-z 0-9
BASE62_ALPHABET = string.ascii_letters + string.digits


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def validate_alias(alias: str) -> None:
    """
    Allow only URL-safe alias characters.
    """
    allowed = set(string.ascii_letters + string.digits + "-_")
    if any(ch not in allowed for ch in alias):
        raise HTTPException(status_code=400, detail="custom_alias contains invalid characters")


def generate_code(length: int) -> str:
    return "".join(secrets.choice(BASE62_ALPHABET) for _ in range(length))


def compute_expires_at(expires_in_days: int | None) -> datetime | None:
    days = expires_in_days if expires_in_days is not None else settings.default_expiry_days
    if days <= 0:
        return None
    return utcnow() + timedelta(days=days)


def is_expired(expires_at: datetime | None) -> bool:
    return expires_at is not None and expires_at <= utcnow()


def redis_ttl_seconds(expires_at: datetime | None) -> int:
    """
    If link expires, align Redis TTL with expiry.
    Otherwise, use a default TTL (e.g., 24h).
    """
    if expires_at is None:
        return settings.redis_default_ttl_seconds
    seconds = int((expires_at - utcnow()).total_seconds())
    return max(1, seconds)


def enforce_rate_limit(ip: str) -> None:
    """
    Simple fixed-window rate limiting (per minute) using Redis:
      rl:{ip}:{YYYYMMDDHHMM} -> INCR + EXPIRE 60
    """
    bucket = utcnow().strftime("%Y%m%d%H%M")
    key = rate_limit_key(ip, bucket)

    current = redis_client.incr(key)
    if current == 1:
        redis_client.expire(key, 60)

    if current > settings.rate_limit_per_minute:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")


def shorten_url(
    db: Session,
    long_url: str,
    custom_alias: str | None,
    expires_in_days: int | None,
) -> UrlMap:
    """
    Creates a short code for a given long URL.
    Writes to Postgres (source of truth) and warms Redis cache.
    """
    if custom_alias:
        validate_alias(custom_alias)

    created = utcnow()
    expires_at = compute_expires_at(expires_in_days)

    # Custom alias path
    if custom_alias:
        existing = db.get(UrlMap, custom_alias)
        if existing is not None:
            raise HTTPException(status_code=409, detail="custom_alias is already taken")

        row = UrlMap(
            code=custom_alias,
            long_url=long_url,
            created_at=created,
            expires_at=expires_at,
            click_count=0,
            last_accessed_at=None,
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        redis_client.setex(cache_key_for_code(row.code), redis_ttl_seconds(expires_at), long_url)
        return row

    # Generated code path with collision retries
    max_tries = 10
    for _ in range(max_tries):
        code = generate_code(settings.code_length)
        if db.get(UrlMap, code) is None:
            row = UrlMap(
                code=code,
                long_url=long_url,
                created_at=created,
                expires_at=expires_at,
                click_count=0,
                last_accessed_at=None,
            )
            db.add(row)
            db.commit()
            db.refresh(row)

            redis_client.setex(cache_key_for_code(row.code), redis_ttl_seconds(expires_at), long_url)
            return row

    raise HTTPException(status_code=500, detail="Failed to generate unique code. Try again.")


def get_long_url_for_redirect(db: Session, code: str) -> str:
    """
    Redirect hot path:
      1) Redis cache lookup
      2) Postgres fallback
      3) Cache warm-up
    """
    cached = redis_client.get(cache_key_for_code(code))
    if cached:
        return cached

    row = db.get(UrlMap, code)
    if row is None:
        raise HTTPException(status_code=404, detail="Short code not found")

    if is_expired(row.expires_at):
        raise HTTPException(status_code=404, detail="Short code expired")

    redis_client.setex(cache_key_for_code(code), redis_ttl_seconds(row.expires_at), row.long_url)
    return row.long_url


def increment_click(code: str) -> None:
    """
    Async-click design:
    Fast path increments Redis counter only.
    A separate worker flushes click:* counts into Postgres in batches.
    """
    redis_client.incr(click_key_for_code(code))


def get_pending_clicks(code: str) -> int:
    """
    Reads pending (not yet flushed) click increments from Redis.
    Used by /stats to show near-real-time counts.
    """
    val = redis_client.get(click_key_for_code(code))
    if val is None:
        return 0
    try:
        return int(val)
    except ValueError:
        return 0


def get_stats(db: Session, code: str) -> UrlMap:
    row = db.get(UrlMap, code)
    if row is None:
        raise HTTPException(status_code=404, detail="Short code not found")
    return row