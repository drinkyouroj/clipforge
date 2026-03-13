"""Export API endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db.models import Clip, Export, Job, User, Video
from app.db.session import get_db
from app.export.schemas import ExportRequest, ExportResponse, ExportListResponse
from app.rendering.specs import get_platform_spec

router = APIRouter(prefix="/exports", tags=["exports"])


@router.post("", response_model=ExportResponse)
async def create_export(
    data: ExportRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create an export and trigger the render pipeline."""
    # Verify clip belongs to user and is selected
    clip_result = await db.execute(
        select(Clip)
        .join(Video, Clip.video_id == Video.id)
        .where(Clip.id == data.clip_id, Video.user_id == user.id)
    )
    clip = clip_result.scalar_one_or_none()
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    if clip.status != "selected":
        raise HTTPException(
            status_code=400,
            detail=f"Clip must be 'selected' to export (current: '{clip.status}')",
        )

    # Credit enforcement: atomic check-and-increment
    from app.billing.service import check_and_increment_credits
    allowed = await check_and_increment_credits(db, user.id, user.subscription_tier)
    if not allowed:
        raise HTTPException(
            status_code=402,
            detail="Export limit reached. Upgrade your plan.",
        )

    # Get platform specs
    spec = get_platform_spec(data.platform)

    # Note: clip duration may exceed platform max — pipeline will truncate
    # to spec["max_duration"] automatically via FFmpeg -t flag. No rejection here.

    # Create job
    job = Job(
        user_id=user.id,
        video_id=clip.video_id,
        job_type="render",
        status="pending",
    )
    db.add(job)
    await db.flush()

    # Create export
    export = Export(
        clip_id=clip.id,
        user_id=user.id,
        platform=data.platform,
        aspect_ratio=spec["aspect_ratio"],
        resolution=f"{spec['width']}x{spec['height']}",
        status="pending",
        job_id=job.id,
    )
    db.add(export)
    await db.commit()
    await db.refresh(export)

    # Enqueue render pipeline
    # Note: matches existing pattern in clip_detection/router.py — commented out
    # until ARQ worker is running. Uncomment when deploying with worker:
    # from arq import create_pool
    # from arq.connections import RedisSettings
    # pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    # await pool.enqueue_job("prepare_render_task", str(export.id))
    # await pool.close()

    return export


@router.get("", response_model=ExportListResponse)
async def list_exports(
    limit: int = 50,
    offset: int = 0,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all exports for the current user."""
    result = await db.execute(
        select(Export)
        .where(Export.user_id == user.id)
        .order_by(Export.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    exports = list(result.scalars().all())

    # Get total count
    count_result = await db.execute(
        select(func.count(Export.id)).where(Export.user_id == user.id)
    )
    total = count_result.scalar()

    return ExportListResponse(exports=exports, total=total)


@router.get("/{export_id}", response_model=ExportResponse)
async def get_export(
    export_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get export status and download URL (user-scoped)."""
    result = await db.execute(
        select(Export).where(Export.id == export_id, Export.user_id == user.id)
    )
    export = result.scalar_one_or_none()
    if not export:
        raise HTTPException(status_code=404, detail="Export not found")
    return export


@router.get("/clip/{clip_id}", response_model=ExportListResponse)
async def get_exports_for_clip(
    clip_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all exports for a clip (user-scoped)."""
    # Verify clip belongs to user
    clip_result = await db.execute(
        select(Clip)
        .join(Video, Clip.video_id == Video.id)
        .where(Clip.id == clip_id, Video.user_id == user.id)
    )
    if not clip_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Clip not found")

    result = await db.execute(
        select(Export)
        .where(Export.clip_id == clip_id, Export.user_id == user.id)
        .order_by(Export.created_at.desc())
    )
    exports = list(result.scalars().all())
    return ExportListResponse(exports=exports, total=len(exports))
