"""Pydantic schemas for export API."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class ExportRequest(BaseModel):
    clip_id: UUID
    platform: Literal["shorts", "tiktok", "reels", "square", "twitter"]


class ExportResponse(BaseModel):
    id: UUID
    clip_id: UUID
    user_id: UUID
    platform: str
    aspect_ratio: str
    resolution: str
    status: str
    job_id: UUID | None
    s3_key: str | None
    download_url: str | None
    expires_at: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True


class ExportListResponse(BaseModel):
    exports: list[ExportResponse]
    total: int
