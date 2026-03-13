from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db.models import Clip, Job, Transcript, User, Video
from app.db.session import get_db
from app.clip_detection.schemas import ClipResponse, ClipListResponse, ClipUpdateRequest

router = APIRouter(prefix="/clips", tags=["clips"])


@router.get("/video/{video_id}", response_model=ClipListResponse)
async def get_clips_for_video(
    video_id: UUID,
    status: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all clip candidates for a video (user-scoped). Optional status filter."""
    # Verify video belongs to user
    video_result = await db.execute(
        select(Video).where(Video.id == video_id, Video.user_id == user.id)
    )
    if not video_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Video not found")

    query = select(Clip).where(Clip.video_id == video_id)
    if status:
        query = query.where(Clip.status == status)
    query = query.order_by(Clip.virality_score.desc().nulls_last())

    result = await db.execute(query)
    clips = list(result.scalars().all())
    return ClipListResponse(clips=clips, total=len(clips))


@router.post("/detect/{video_id}")
async def trigger_clip_detection(
    video_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger clip detection for a video. Creates a detect_clips job."""
    video_result = await db.execute(
        select(Video).where(Video.id == video_id, Video.user_id == user.id)
    )
    video = video_result.scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    # Check transcript exists
    transcript_result = await db.execute(
        select(Transcript).where(Transcript.video_id == video_id)
    )
    if not transcript_result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Video has no transcript yet")

    # Create job
    job = Job(
        user_id=user.id,
        video_id=video_id,
        job_type="detect_clips",
        status="pending",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # TODO: enqueue ARQ task here when worker is running
    # await arq_pool.enqueue_job("detect_clips_task", str(video_id), str(user.id))

    return {"job_id": str(job.id), "status": "pending"}


@router.get("/{clip_id}", response_model=ClipResponse)
async def get_clip(
    clip_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single clip (user-scoped via video ownership)."""
    result = await db.execute(
        select(Clip)
        .join(Video, Clip.video_id == Video.id)
        .where(Clip.id == clip_id, Video.user_id == user.id)
    )
    clip = result.scalar_one_or_none()
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    return clip


@router.patch("/{clip_id}", response_model=ClipResponse)
async def update_clip(
    clip_id: UUID,
    data: ClipUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update clip boundaries or status (user-scoped)."""
    result = await db.execute(
        select(Clip)
        .join(Video, Clip.video_id == Video.id)
        .where(Clip.id == clip_id, Video.user_id == user.id)
    )
    clip = result.scalar_one_or_none()
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    if data.start_time is not None:
        clip.start_time = data.start_time
    if data.end_time is not None:
        clip.end_time = data.end_time
    if data.start_time is not None or data.end_time is not None:
        clip.duration = clip.end_time - clip.start_time
    if data.status is not None:
        # Per DECISION_006: only candidate↔selected allowed via API
        allowed_transitions = {
            ("candidate", "selected"),
            ("selected", "candidate"),
        }
        if (clip.status, data.status) not in allowed_transitions:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot transition from '{clip.status}' to '{data.status}'",
            )
        clip.status = data.status

    await db.commit()
    await db.refresh(clip)
    return clip
