from __future__ import annotations

import time
from datetime import datetime, timezone

from sqlalchemy import text

from app.config import settings
from app.db import engine
from app.cache import redis_client

CLICK_PREFIX = "click:"


def utcnow():
    return datetime.now(timezone.utc)


def flush_clicks_once() -> int:
    """
    Scan Redis for click:* keys, atomically read+delete their counts,
    then batch-apply increments to Postgres.
    """
    flushed = 0
    cursor = 0
    keys_to_process: list[str] = []

    # 1) Collect keys (SCAN is safe for production; better than KEYS)
    while True:
        cursor, keys = redis_client.scan(cursor=cursor, match=f"{CLICK_PREFIX}*", count=500)
        if keys:
            keys_to_process.extend(keys)
        if cursor == 0:
            break

    if not keys_to_process:
        return 0

    now = utcnow()

    # 2) Pipeline: get counts then delete keys (so we don't double-count)
    pipe = redis_client.pipeline()
    for k in keys_to_process:
        pipe.get(k)
    for k in keys_to_process:
        pipe.delete(k)
    results = pipe.execute()

    counts = results[: len(keys_to_process)]

    # 3) Apply updates to Postgres
    updates: list[tuple[str, int]] = []
    for key, val in zip(keys_to_process, counts):
        if val is None:
            continue
        try:
            delta = int(val)
        except ValueError:
            continue
        if delta <= 0:
            continue

        code = key[len(CLICK_PREFIX) :]
        updates.append((code, delta))

    if not updates:
        return 0

    stmt = text("""
        UPDATE url_map
        SET
            click_count = click_count + :delta,
            last_accessed_at = :now
        WHERE code = :code
    """)

    with engine.begin() as conn:
        for code, delta in updates:
            conn.execute(stmt, {"code": code, "delta": delta, "now": now})
            flushed += delta

    return flushed


def main() -> None:
    print(f"[worker] starting flush loop every {settings.flush_interval_seconds}s")
    while True:
        try:
            n = flush_clicks_once()
            if n:
                print(f"[worker] flushed {n} clicks to Postgres")
        except Exception as e:
            print(f"[worker] error during flush: {e}")
        time.sleep(settings.flush_interval_seconds)


if __name__ == "__main__":
    main()