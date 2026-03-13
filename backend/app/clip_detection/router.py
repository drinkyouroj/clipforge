from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db.models import Clip, User, Video
from app.db.session import get_db
from app.clip_detection.schemas import ClipResponse, ClipListResponse, ClipUpdateRequest

router = APIRouter(prefix="/clips", tags=["clips"])


@router.get("/video/{video_id}", response_model=ClipListResponse)
async def get_clips_for_video(
    video_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all clip candidates for a video (user-scoped)."""
    # Verify video belongs to user
    video_result = await db.execute(
        select(Video).where(Video.id == video_id, Video.user_id == user.id)
    )
    if not video_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Video not found")

    result = await db.execute(
        select(Clip)
        .where(Clip.video_id == video_id)
        .order_by(Clip.virality_score.desc().nulls_last())
    )
    clips = list(result.scalars().all())
    return ClipListResponse(clips=clips, total=len(clips))


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
        clip.status = data.status

    await db.commit()
    await db.refresh(clip)
    return clip
