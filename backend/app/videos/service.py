import os
import tempfile
from datetime import datetime, timedelta
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Video
from app.videos.storage import generate_s3_key, upload_file_to_s3, delete_s3_object
from app.videos.validation import validate_magic_bytes, validate_with_ffprobe

TEMP_DIR = "/tmp/clipforge"


def _ensure_temp_dir():
    os.makedirs(TEMP_DIR, exist_ok=True)


async def check_upload_rate_limit(db: AsyncSession, user_id: UUID) -> bool:
    one_hour_ago = datetime.utcnow() - timedelta(hours=1)
    result = await db.execute(
        select(func.count(Video.id)).where(
            Video.user_id == user_id,
            Video.uploaded_at >= one_hour_ago,
        )
    )
    count = result.scalar()
    return count < settings.upload_rate_limit


async def upload_video(
    db: AsyncSession, user_id: UUID, file: UploadFile
) -> tuple[Video, str | None]:
    """Upload a video. Returns (video, error_message). error_message is None on success."""
    _ensure_temp_dir()
    temp_path = None

    try:
        # Save to temp file
        with tempfile.NamedTemporaryFile(
            dir=TEMP_DIR, delete=False, suffix=os.path.splitext(file.filename or ".mp4")[1]
        ) as tmp:
            temp_path = tmp.name
            content = await file.read()
            if len(content) > settings.max_upload_size:
                return None, "file_too_large"
            tmp.write(content)

        # Validate magic bytes
        if not validate_magic_bytes(temp_path):
            return None, "invalid_type"

        # Validate with ffprobe
        probe_data = validate_with_ffprobe(temp_path)
        if probe_data is None:
            return None, "invalid_video"

        # Upload to S3
        s3_key = generate_s3_key(user_id, file.filename or "upload.mp4")
        await upload_file_to_s3(temp_path, s3_key)

        # Create DB record
        try:
            video = Video(
                user_id=user_id,
                original_filename=file.filename or "upload.mp4",
                s3_key=s3_key,
                file_size=len(content),
                duration=probe_data["duration"],
                mime_type=file.content_type,
                status="uploaded",
            )
            db.add(video)
            await db.commit()
            await db.refresh(video)
            return video, None
        except Exception:
            # DB insert failed — clean up S3 object per DECISION_003
            await delete_s3_object(s3_key)
            raise

    finally:
        # Always clean up temp file
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


async def list_user_videos(db: AsyncSession, user_id: UUID) -> list[Video]:
    result = await db.execute(
        select(Video).where(
            Video.user_id == user_id,
            Video.deleted_at.is_(None),
        ).order_by(Video.created_at.desc())
    )
    return list(result.scalars().all())


async def get_user_video(db: AsyncSession, user_id: UUID, video_id: UUID) -> Video | None:
    result = await db.execute(
        select(Video).where(
            Video.id == video_id,
            Video.user_id == user_id,
            Video.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def soft_delete_video(db: AsyncSession, user_id: UUID, video_id: UUID) -> bool:
    video = await get_user_video(db, user_id, video_id)
    if not video:
        return False
    video.deleted_at = datetime.utcnow()
    video.status = "deleted"
    await db.commit()
    return True
