from pydantic import BaseModel
from uuid import UUID
from datetime import datetime


class VideoResponse(BaseModel):
    id: UUID
    original_filename: str
    file_size: int
    duration: float | None
    status: str
    uploaded_at: datetime

    class Config:
        from_attributes = True


class VideoUploadResponse(BaseModel):
    id: UUID
    original_filename: str
    file_size: int
    duration: float | None
    status: str
    uploaded_at: datetime
    job_id: UUID | None = None

    class Config:
        from_attributes = True


class VideoListResponse(BaseModel):
    videos: list[VideoResponse]
    total: int
