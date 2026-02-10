from datetime import datetime
from pydantic import BaseModel, Field, HttpUrl

class ShortenRequest(BaseModel):
    long_url: HttpUrl
    custom_alias: str | None = Field(default=None, min_length=3, max_length=32)
    expires_in_days: int | None = Field(default=None, ge=1, le=365)

class ShortenResponse(BaseModel):
    code: str
    short_url: str
    expires_at: datetime | None

class StatsResponse(BaseModel):
    code: str
    long_url: str
    created_at: datetime
    expires_at: datetime | None
    click_count: int
    last_accessed_at: datetime | None