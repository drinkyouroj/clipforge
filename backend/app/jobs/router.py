from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db.models import Job, User, Video
from app.db.session import get_db
from app.jobs.schemas import JobResponse

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobResponse)
async def get_job_status(
    job_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Job)
        .join(Video, Job.video_id == Video.id)
        .where(Job.id == job_id, Video.user_id == user.id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/video/{video_id}", response_model=list[JobResponse])
async def get_jobs_for_video(
    video_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Job)
        .join(Video, Job.video_id == Video.id)
        .where(Job.video_id == video_id, Video.user_id == user.id)
    )
    return result.scalars().all()
