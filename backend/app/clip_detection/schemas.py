from pydantic import BaseModel
from uuid import UUID
from datetime import datetime


class ClipResponse(BaseModel):
    id: UUID
    video_id: UUID
    start_time: float
    end_time: float
    duration: float
    virality_score: int | None
    hook: str | None
    reasoning: str | None
    clip_type: str | None
    suggested_title: str | None
    platform_fit: list[str] | None
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class ClipListResponse(BaseModel):
    clips: list[ClipResponse]
    total: int


class ClipUpdateRequest(BaseModel):
    start_time: float | None = None
    end_time: float | None = None
    status: str | None = None
