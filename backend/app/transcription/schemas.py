from pydantic import BaseModel
from uuid import UUID
from datetime import datetime


class TranscriptResponse(BaseModel):
    id: UUID
    video_id: UUID
    content: str
    word_timestamps: list | None
    language: str | None
    created_at: datetime

    class Config:
        from_attributes = True
