from __future__ import annotations

import time
from fastapi import FastAPI, Depends, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.db import Base, engine, get_db
from app.config import settings
from app.schemas import ShortenRequest, ShortenResponse, StatsResponse
from app.service import (
    shorten_url,
    get_long_url_for_redirect,
    increment_click,
    get_stats,
    enforce_rate_limit,
    get_pending_clicks,
)
from app.ui import ui_page

app = FastAPI(title="URL Shortener (SDE Project)")


@app.on_event("startup")
def on_startup() -> None:
    """
    Wait for Postgres to be reachable before creating tables.
    This avoids 'connection refused' when containers start in parallel.
    """
    max_attempts = 30
    sleep_seconds = 1

    last_err: Exception | None = None
    for _ in range(max_attempts):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            last_err = None
            break
        except Exception as e:
            last_err = e
            time.sleep(sleep_seconds)

    if last_err is not None:
        raise RuntimeError(f"Database not reachable after {max_attempts} attempts") from last_err

    # MVP: create tables automatically (later: Alembic migrations)
    Base.metadata.create_all(bind=engine)


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    # Nice default: open the UI instead of JSON
    return RedirectResponse(url="/ui", status_code=302)


@app.get("/ui", include_in_schema=False)
def ui() -> HTMLResponse:
    return ui_page()


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "url-shortener",
        "base_url": settings.base_url,
    }


@app.post("/shorten", response_model=ShortenResponse)
def create_short_url(
    payload: ShortenRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> ShortenResponse:
    # Rate limit based on client IP (simple MVP). Behind proxies you'd read X-Forwarded-For safely.
    ip = request.client.host if request.client else "unknown"
    enforce_rate_limit(ip)

    row = shorten_url(
        db=db,
        long_url=str(payload.long_url),
        custom_alias=payload.custom_alias,
        expires_in_days=payload.expires_in_days,
    )

    return ShortenResponse(
        code=row.code,
        short_url=f"{settings.base_url}/{row.code}",
        expires_at=row.expires_at,
    )


@app.get("/stats/{code}", response_model=StatsResponse)
def stats(code: str, db: Session = Depends(get_db)) -> StatsResponse:
    """
    Stats shows:
      DB click_count (already flushed)
    + pending Redis clicks (not yet flushed by worker)
    for near-real-time numbers.
    """
    row = get_stats(db, code)

    pending = get_pending_clicks(code)
    total_clicks = row.click_count + pending

    return StatsResponse(
        code=row.code,
        long_url=row.long_url,
        created_at=row.created_at,
        expires_at=row.expires_at,
        click_count=total_clicks,
        last_accessed_at=row.last_accessed_at,
    )


@app.get("/{code}")
def redirect(code: str, db: Session = Depends(get_db)) -> RedirectResponse:
    """
    Redirect hot path:
    - Resolve long_url via Redis -> Postgres fallback
    - Increment click counter in Redis (async flush by worker)
    """
    long_url = get_long_url_for_redirect(db, code)

    # Async click: Redis INCR only (fast)
    increment_click(code)

    return RedirectResponse(url=long_url, status_code=302)