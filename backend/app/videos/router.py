from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db.models import User, Video
from app.db.session import get_db
from app.videos.schemas import VideoListResponse, VideoResponse, VideoUploadResponse
from app.videos.service import (
    check_upload_rate_limit,
    list_user_videos,
    get_user_video,
    soft_delete_video,
    upload_video,
)

router = APIRouter(prefix="/videos", tags=["videos"])


@router.post("/upload", response_model=VideoUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload(
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not await check_upload_rate_limit(db, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Upload rate limit exceeded (5 per hour)",
        )

    video, error = await upload_video(db, current_user.id, file)

    if error == "file_too_large":
        raise HTTPException(status_code=413, detail="File exceeds 500MB limit")
    if error == "invalid_type":
        raise HTTPException(status_code=415, detail="File is not a supported video format")
    if error == "invalid_video":
        raise HTTPException(status_code=422, detail="File is not a valid video or missing audio track")
    if error:
        raise HTTPException(status_code=500, detail="Upload failed")

    return video


@router.get("/", response_model=VideoListResponse)
async def list_videos(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    videos = await list_user_videos(db, current_user.id)
    return VideoListResponse(videos=videos, total=len(videos))


@router.get("/{video_id}", response_model=VideoResponse)
async def get_video(
    video_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    video = await get_user_video(db, current_user.id, video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    return video


@router.delete("/{video_id}", status_code=status.HTTP_200_OK)
async def delete_video(
    video_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    deleted = await soft_delete_video(db, current_user.id, video_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Video not found")
    return {"message": "Video deleted"}


@router.get("/{video_id}/preview-url")
async def get_preview_url(
    video_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a short-lived presigned URL for in-browser video preview."""
    result = await db.execute(
        select(Video).where(Video.id == video_id, Video.user_id == current_user.id)
    )
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    from app.videos.storage import generate_presigned_url
    url = generate_presigned_url(video.s3_key, expires_in=900)  # 15 minutes
    return {"url": url}
