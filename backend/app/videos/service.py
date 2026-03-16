import os
import tempfile
from datetime import datetime, timedelta
from uuid import UUID

from arq.connections import ArqRedis, create_pool, RedisSettings
from fastapi import UploadFile
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Clip, Export, Job, Video
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
) -> tuple[Video | None, str | None, UUID | None]:
    """Upload a video. Returns (video, error_message). error_message is None on success."""
    _ensure_temp_dir()
    temp_path = None

    try:
        # Stream to temp file in chunks to avoid loading entire file in memory
        with tempfile.NamedTemporaryFile(
            dir=TEMP_DIR, delete=False, suffix=os.path.splitext(file.filename or ".mp4")[1]
        ) as tmp:
            temp_path = tmp.name
            file_size = 0
            chunk_size = 8 * 1024 * 1024  # 8MB chunks
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                file_size += len(chunk)
                if file_size > settings.max_upload_size:
                    return None, "file_too_large", None
                tmp.write(chunk)

        # Validate magic bytes
        if not validate_magic_bytes(temp_path):
            return None, "invalid_type", None

        # Validate with ffprobe
        probe_data = validate_with_ffprobe(temp_path)
        if probe_data is None:
            return None, "invalid_video", None

        # Upload to S3
        s3_key = generate_s3_key(user_id, file.filename or "upload.mp4")
        await upload_file_to_s3(temp_path, s3_key)

        # Create DB record
        try:
            video = Video(
                user_id=user_id,
                original_filename=file.filename or "upload.mp4",
                s3_key=s3_key,
                file_size=file_size,
                duration=probe_data["duration"],
                mime_type=file.content_type,
                status="uploaded",
            )
            db.add(video)
            await db.flush()

            # Create transcription job and enqueue it
            job = Job(
                video_id=video.id,
                job_type="transcribe",
                status="pending",
            )
            db.add(job)
            await db.commit()
            await db.refresh(video)
            await db.refresh(job)

            # Enqueue ARQ task
            redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
            await redis.enqueue_job("transcribe_video", str(job.id), str(video.id))
            await redis.aclose()

            return video, None, job.id
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
    """Soft-delete video with immediate S3 cleanup.

    - Sets deleted_at on the Video record
    - Deletes source S3 object immediately
    - Deletes all export S3 objects for this video's clips
    - Cancels in-progress/pending jobs
    - DB records remain for 7 days (purged by daily cleanup)
    """
    video = await get_user_video(db, user_id, video_id)
    if not video:
        return False

    # 1. Soft-delete the video record
    video.deleted_at = datetime.utcnow()
    video.status = "deleted"

    # 2. Delete source S3 object
    try:
        await delete_s3_object(video.s3_key)
    except Exception:
        pass  # Log but don't block — safety net catches on hard-delete

    # 3. Find and delete export S3 objects
    clip_result = await db.execute(
        select(Clip.id).where(Clip.video_id == video_id)
    )
    clip_ids = [row[0] for row in clip_result.all()]

    if clip_ids:
        export_result = await db.execute(
            select(Export).where(Export.clip_id.in_(clip_ids))
        )
        for export in export_result.scalars().all():
            if export.s3_key:
                try:
                    await delete_s3_object(export.s3_key)
                except Exception:
                    pass

    # 4. Cancel pending/running jobs
    job_result = await db.execute(
        select(Job).where(
            Job.video_id == video_id,
            Job.status.in_(["pending", "running"]),
        )
    )
    for job in job_result.scalars().all():
        job.status = "failed"
        job.error_message = "Video deleted by user"
        job.completed_at = datetime.utcnow()

    await db.commit()
    return True
