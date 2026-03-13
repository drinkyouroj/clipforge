from pydantic import BaseModel
from uuid import UUID
from datetime import datetime


class JobResponse(BaseModel):
    id: UUID
    job_type: str
    status: str
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    class Config:
        from_attributes = True
