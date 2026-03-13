import os
import tempfile
from datetime import datetime, timezone, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.config import settings
from app.db.models import Clip, Job, Transcript, Video
from app.transcription.audio import extract_audio
from app.transcription.service import transcribe_audio
from app.videos.storage import download_from_s3, delete_s3_object

TEMP_DIR = "/tmp/clipforge"


def _ensure_temp_dir():
    os.makedirs(TEMP_DIR, exist_ok=True)


def _cleanup_old_temp_files():
    """Sweep /tmp/clipforge/ for files and directories older than 1 hour.

    Walks two levels deep to handle render/{job_id}/ subdirectories,
    since the render/ parent dir mtime refreshes when new jobs are created.
    """
    import shutil

    if not os.path.exists(TEMP_DIR):
        return
    now = datetime.now(timezone.utc).timestamp()
    for entry in os.listdir(TEMP_DIR):
        path = os.path.join(TEMP_DIR, entry)
        try:
            if os.path.isdir(path):
                # Walk into subdirectories (e.g., render/) to find old job dirs
                for sub_entry in os.listdir(path):
                    sub_path = os.path.join(path, sub_entry)
                    try:
                        if (now - os.path.getmtime(sub_path)) > 3600:
                            if os.path.isdir(sub_path):
                                shutil.rmtree(sub_path)
                            else:
                                os.unlink(sub_path)
                    except OSError:
                        pass
                # Remove parent dir only if empty AND itself is old
                try:
                    if not os.listdir(path) and (now - os.path.getmtime(path)) > 3600:
                        os.rmdir(path)
                except OSError:
                    pass
            elif os.path.isfile(path) and (now - os.path.getmtime(path)) > 3600:
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


async def detect_clips_task(ctx, video_id: str, user_id: str):
    """ARQ task: run clip detection on a transcribed video."""
    from app.clip_detection.detector import detect_clips, detect_clips_long_video

    db = await _get_db_session()

    try:
        vid_uuid = UUID(video_id)
        usr_uuid = UUID(user_id)

        # Find pending detect_clips job
        job_result = await db.execute(
            select(Job).where(
                Job.video_id == vid_uuid,
                Job.user_id == usr_uuid,
                Job.job_type == "detect_clips",
                Job.status == "pending",
            )
        )
        job = job_result.scalar_one_or_none()
        if not job:
            return

        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        await db.commit()

        # Fetch video and transcript
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

        transcript_result = await db.execute(
            select(Transcript).where(Transcript.video_id == vid_uuid)
        )
        transcript = transcript_result.scalar_one_or_none()
        if not transcript:
            job.status = "failed"
            job.error_message = "Transcript not found"
            job.completed_at = datetime.now(timezone.utc)
            await db.commit()
            return

        # Run clip detection
        word_timestamps = transcript.word_timestamps or []
        video_duration = video.duration or 0.0

        if video_duration > 3600:  # > 60 minutes
            result = await detect_clips_long_video(
                transcript.content, word_timestamps, video_duration
            )
        else:
            result = await detect_clips(
                transcript.content, word_timestamps, video_duration
            )

        # Store clip candidates in DB
        clips_data = result.get("clips", [])
        if not clips_data:
            job.status = "failed"
            job.error_message = "No valid clips detected"
            job.completed_at = datetime.now(timezone.utc)
            await db.commit()
            return

        for clip_data in clips_data:
            clip = Clip(
                video_id=vid_uuid,
                transcript_id=transcript.id,
                start_time=clip_data["start_time"],
                end_time=clip_data["end_time"],
                duration=clip_data["duration"],
                virality_score=clip_data.get("virality_score"),
                hook=clip_data.get("hook"),
                reasoning=clip_data.get("reasoning"),
                clip_type=clip_data.get("clip_type"),
                suggested_title=clip_data.get("suggested_title"),
                platform_fit=clip_data.get("platform_fit"),
                status="candidate",
            )
            db.add(clip)

        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)
        await db.commit()

    except Exception as e:
        try:
            if db:
                job_result = await db.execute(
                    select(Job).where(
                        Job.video_id == UUID(video_id),
                        Job.job_type == "detect_clips",
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
        if db:
            await db.close()


async def cleanup_expired_content(ctx):
    """Daily cleanup task — auto-expire, hard-delete, and reset billing periods.

    1. Auto-expire videos older than 30 days (S3 cleanup + soft delete)
    2. Hard-delete videos soft-deleted more than 7 days ago
    3. Reset period_exports_used for users with expired billing periods
    """
    import logging
    from dateutil.relativedelta import relativedelta
    from app.db.models import Clip, Export, Job, Transcript, User, Video

    logger = logging.getLogger(__name__)
    db = await _get_db_session()

    try:
        now = datetime.now(timezone.utc)
        thirty_days_ago = now - timedelta(days=30)
        seven_days_ago = now - timedelta(days=7)

        # --- 1. Auto-expire old videos (30+ days) ---
        result = await db.execute(
            select(Video).where(
                Video.deleted_at.is_(None),
                Video.created_at < thirty_days_ago,
            )
        )
        old_videos = list(result.scalars().all())

        for video in old_videos:
            # Skip if any jobs are still running
            running_jobs = await db.execute(
                select(Job).where(
                    Job.video_id == video.id,
                    Job.status == "running",
                )
            )
            if running_jobs.scalar_one_or_none():
                logger.info(f"Cleanup: skipping video {video.id} — running jobs")
                continue

            try:
                # Delete source S3 object
                try:
                    await delete_s3_object(video.s3_key)
                except Exception:
                    pass

                # Delete export S3 objects
                clip_result = await db.execute(
                    select(Clip.id).where(Clip.video_id == video.id)
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

                # Cancel pending/running jobs
                job_result = await db.execute(
                    select(Job).where(
                        Job.video_id == video.id,
                        Job.status.in_(["pending", "running"]),
                    )
                )
                for job in job_result.scalars().all():
                    job.status = "failed"
                    job.error_message = "Video auto-expired (30 days)"
                    job.completed_at = now

                # Soft-delete
                video.deleted_at = now
                video.status = "deleted"
                await db.commit()
                logger.info(f"Cleanup: auto-expired video {video.id}")

            except Exception as e:
                await db.rollback()
                logger.error(f"Cleanup: failed to auto-expire video {video.id}: {e}")

        # --- 2. Hard-delete old soft-deleted videos (7+ days) ---
        result = await db.execute(
            select(Video).where(
                Video.deleted_at.isnot(None),
                Video.deleted_at < seven_days_ago,
            )
        )
        deleted_videos = list(result.scalars().all())

        for video in deleted_videos:
            try:
                # Safety-net S3 delete
                try:
                    await delete_s3_object(video.s3_key)
                except Exception:
                    pass

                # Delete in dependency order: exports → clips → transcript → jobs → video
                clip_result = await db.execute(
                    select(Clip.id).where(Clip.video_id == video.id)
                )
                clip_ids = [row[0] for row in clip_result.all()]

                if clip_ids:
                    # Delete exports and their S3 objects
                    export_result = await db.execute(
                        select(Export).where(Export.clip_id.in_(clip_ids))
                    )
                    for export in export_result.scalars().all():
                        if export.s3_key:
                            try:
                                await delete_s3_object(export.s3_key)
                            except Exception:
                                pass
                        await db.delete(export)

                    # Delete clips
                    for clip_id in clip_ids:
                        clip_obj_result = await db.execute(
                            select(Clip).where(Clip.id == clip_id)
                        )
                        clip_obj = clip_obj_result.scalar_one_or_none()
                        if clip_obj:
                            await db.delete(clip_obj)

                # Delete transcript
                transcript_result = await db.execute(
                    select(Transcript).where(Transcript.video_id == video.id)
                )
                transcript = transcript_result.scalar_one_or_none()
                if transcript:
                    await db.delete(transcript)

                # Delete jobs
                job_result = await db.execute(
                    select(Job).where(Job.video_id == video.id)
                )
                for job in job_result.scalars().all():
                    await db.delete(job)

                # Delete video
                await db.delete(video)
                await db.commit()
                logger.info(f"Cleanup: hard-deleted video {video.id}")

            except Exception as e:
                await db.rollback()
                logger.error(f"Cleanup: failed to hard-delete video {video.id}: {e}")

        # --- 3. Reset expired billing periods ---
        result = await db.execute(
            select(User).where(
                User.current_period_end.isnot(None),
                User.current_period_end < now,
            )
        )
        expired_users = list(result.scalars().all())

        for user in expired_users:
            user.period_exports_used = 0
            # Advance period by 1 month
            user.current_period_end = user.current_period_end + relativedelta(months=1)
            logger.info(f"Cleanup: reset billing period for user {user.id}")

        if expired_users:
            await db.commit()

    finally:
        await db.close()
