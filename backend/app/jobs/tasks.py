import os
import tempfile
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.config import settings
from app.db.models import Job, Transcript, Video
from app.transcription.audio import extract_audio
from app.transcription.service import transcribe_audio
from app.videos.storage import download_from_s3

TEMP_DIR = "/tmp/clipforge"


def _ensure_temp_dir():
    os.makedirs(TEMP_DIR, exist_ok=True)


def _cleanup_old_temp_files():
    """Sweep /tmp/clipforge/ for files older than 1 hour (per DECISION_004)."""
    if not os.path.exists(TEMP_DIR):
        return
    now = datetime.now(timezone.utc).timestamp()
    for f in os.listdir(TEMP_DIR):
        path = os.path.join(TEMP_DIR, f)
        try:
            if os.path.isfile(path) and (now - os.path.getmtime(path)) > 3600:
                os.unlink(path)
        except OSError:
            pass


async def _get_db_session() -> AsyncSession:
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    session = session_factory()
    return session


async def transcribe_video(ctx, video_id: str, user_id: str):
    """ARQ task: extract audio, transcribe via Whisper, store transcript."""
    _ensure_temp_dir()
    _cleanup_old_temp_files()

    db = await _get_db_session()
    temp_video_path = None
    temp_audio_path = None

    try:
        vid_uuid = UUID(video_id)
        usr_uuid = UUID(user_id)

        # Update job status to running
        job_result = await db.execute(
            select(Job).where(
                Job.video_id == vid_uuid,
                Job.user_id == usr_uuid,
                Job.job_type == "transcribe",
                Job.status == "pending",
            )
        )
        job = job_result.scalar_one_or_none()
        if not job:
            return

        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        await db.commit()

        # Fetch video record
        video_result = await db.execute(
            select(Video).where(Video.id == vid_uuid, Video.user_id == usr_uuid)
        )
        video = video_result.scalar_one_or_none()
        if not video:
            job.status = "failed"
            job.error_message = "Video not found"
            job.completed_at = datetime.now(timezone.utc)
            await db.commit()
            return

        # Download video from S3 to temp file
        suffix = os.path.splitext(video.original_filename or ".mp4")[1]
        with tempfile.NamedTemporaryFile(
            dir=TEMP_DIR, delete=False, suffix=suffix
        ) as tmp:
            temp_video_path = tmp.name

        await download_from_s3(video.s3_key, temp_video_path)

        # Extract audio
        temp_audio_path = temp_video_path + ".mp3"
        extract_audio(temp_video_path, temp_audio_path)

        # Transcribe
        result = transcribe_audio(temp_audio_path)
        # Handle both sync and async
        if hasattr(result, "__await__"):
            result = await result

        # Store transcript
        transcript = Transcript(
            video_id=vid_uuid,
            content=result.get("text", ""),
            word_timestamps=result.get("words", []),
            language=result.get("language", "en"),
        )
        db.add(transcript)

        # Update video status
        video.status = "ready"

        # Update job status
        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)

        await db.commit()

    except Exception as e:
        # Mark job as failed
        try:
            if db:
                job_result = await db.execute(
                    select(Job).where(
                        Job.video_id == UUID(video_id),
                        Job.job_type == "transcribe",
                        Job.status == "running",
                    )
                )
                job = job_result.scalar_one_or_none()
                if job:
                    job.status = "failed"
                    job.error_message = str(e)[:500]
                    job.completed_at = datetime.now(timezone.utc)
                    await db.commit()
        except Exception:
            pass
        raise

    finally:
        # Clean up temp files
        for path in [temp_video_path, temp_audio_path]:
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except OSError:
                    pass
        if db:
            await db.close()
