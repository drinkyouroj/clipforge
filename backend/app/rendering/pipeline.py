"""Three-step render pipeline: prepare → execute → upload."""

import json
import logging
import os
import shutil
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.config import settings
from app.db.models import Clip, Export, Job, Transcript, Video
from app.videos.storage import download_from_s3, upload_file_to_s3, generate_presigned_url

logger = logging.getLogger(__name__)

RENDER_TEMP_BASE = "/tmp/clipforge/render"


async def _get_db_session() -> AsyncSession:
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return session_factory()


def _get_temp_dir(job_id: str) -> str:
    path = os.path.join(RENDER_TEMP_BASE, job_id)
    os.makedirs(path, exist_ok=True)
    return path


def _cleanup_temp_dir(job_id: str):
    path = os.path.join(RENDER_TEMP_BASE, job_id)
    if os.path.exists(path):
        shutil.rmtree(path, ignore_errors=True)


async def _fail_export(db: AsyncSession, export: Export, job: Job, error: str, job_id_str: str):
    """Mark export and job as failed, clean up."""
    job.status = "failed"
    job.error_message = str(error)[:500]
    job.completed_at = datetime.now(timezone.utc)
    export.status = "failed"
    await db.commit()
    _cleanup_temp_dir(job_id_str)


async def prepare_render_task(ctx, export_id: str):
    """Step 1: Download video, run face detection, generate ASS captions."""
    from app.rendering.reframe import build_face_track
    from app.rendering.captions import generate_ass_captions
    from app.rendering.specs import get_platform_spec

    db = await _get_db_session()
    try:
        exp_uuid = UUID(export_id)

        # Load export + job + clip + video + transcript
        export_result = await db.execute(
            select(Export).where(Export.id == exp_uuid)
        )
        export = export_result.scalar_one_or_none()
        if not export:
            return

        job_result = await db.execute(select(Job).where(Job.id == export.job_id))
        job = job_result.scalar_one_or_none()
        if not job:
            return

        clip_result = await db.execute(select(Clip).where(Clip.id == export.clip_id))
        clip = clip_result.scalar_one_or_none()

        video_result = await db.execute(select(Video).where(Video.id == clip.video_id))
        video = video_result.scalar_one_or_none()

        transcript_result = await db.execute(
            select(Transcript).where(Transcript.video_id == video.id)
        )
        transcript = transcript_result.scalar_one_or_none()

        # Update status
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        export.status = "rendering"
        await db.commit()

        job_id_str = str(job.id)
        temp_dir = _get_temp_dir(job_id_str)

        # Download video
        input_path = os.path.join(temp_dir, "input.mp4")
        await download_from_s3(video.s3_key, input_path)

        if not os.path.exists(input_path):
            await _fail_export(db, export, job, "Failed to download video from S3", job_id_str)
            return

        # Face detection (reuse cached track if available)
        if clip.face_track is None or not clip.face_track.get("frames"):
            face_track = build_face_track(input_path, clip.start_time, clip.duration)
            clip.face_track = face_track
            await db.commit()

        # Generate ASS captions (pass output resolution for correct PlayRes)
        spec = get_platform_spec(export.platform)

        word_timestamps = transcript.word_timestamps if transcript else []
        ass_content = generate_ass_captions(
            word_timestamps, clip_start_time=clip.start_time,
            play_res_x=spec["width"], play_res_y=spec["height"],
        )
        ass_path = os.path.join(temp_dir, "captions.ass")
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(ass_content)

        # Store render context
        job.render_context = {
            "temp_dir": temp_dir,
            "input_path": input_path,
            "ass_path": ass_path,
            "export_id": export_id,
        }
        await db.commit()

        # Enqueue next step
        from arq import create_pool
        from arq.connections import RedisSettings

        pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        await pool.enqueue_job("execute_render_task", export_id)
        await pool.close()

    except Exception as e:
        try:
            export_result = await db.execute(select(Export).where(Export.id == UUID(export_id)))
            export = export_result.scalar_one_or_none()
            job_result = await db.execute(select(Job).where(Job.id == export.job_id)) if export else None
            job = job_result.scalar_one_or_none() if job_result else None
            if export and job:
                await _fail_export(db, export, job, str(e), str(job.id))
        except Exception:
            pass
        raise
    finally:
        await db.close()


async def execute_render_task(ctx, export_id: str):
    """Step 2: Build and run FFmpeg command."""
    import asyncio
    from app.rendering.ffmpeg_cmd import build_ffmpeg_command
    from app.rendering.reframe import compute_crop_params
    from app.rendering.specs import get_platform_spec

    db = await _get_db_session()
    try:
        exp_uuid = UUID(export_id)

        export_result = await db.execute(select(Export).where(Export.id == exp_uuid))
        export = export_result.scalar_one_or_none()
        if not export:
            return

        job_result = await db.execute(select(Job).where(Job.id == export.job_id))
        job = job_result.scalar_one_or_none()
        if not job or not job.render_context:
            return

        clip_result = await db.execute(select(Clip).where(Clip.id == export.clip_id))
        clip = clip_result.scalar_one_or_none()

        video_result = await db.execute(select(Video).where(Video.id == clip.video_id))
        video = video_result.scalar_one_or_none()

        ctx_data = job.render_context
        input_path = ctx_data["input_path"]
        ass_path = ctx_data["ass_path"]
        temp_dir = ctx_data["temp_dir"]

        # Get platform specs
        spec = get_platform_spec(export.platform)

        # Get video dimensions via ffprobe
        import subprocess
        probe_result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_streams", input_path,
            ],
            capture_output=True, text=True, timeout=30,
        )
        probe = json.loads(probe_result.stdout)
        video_stream = next(
            (s for s in probe.get("streams", []) if s["codec_type"] == "video"), None
        )
        if not video_stream:
            await _fail_export(db, export, job, "No video stream in input file", str(job.id))
            return

        video_width = int(video_stream["width"])
        video_height = int(video_stream["height"])

        # Compute crop
        crop_params = compute_crop_params(
            face_track=clip.face_track,
            video_width=video_width,
            video_height=video_height,
            aspect_ratio=spec["aspect_ratio"],
        )

        # Clamp duration to platform max
        clip_duration = min(clip.duration, spec["max_duration"])

        # Build FFmpeg command
        output_path = os.path.join(temp_dir, "output.mp4")
        cmd = build_ffmpeg_command(
            input_path=input_path,
            output_path=output_path,
            start_time=clip.start_time,
            duration=clip_duration,
            crop=crop_params,
            width=spec["width"],
            height=spec["height"],
            fps=spec["fps"],
            aspect_ratio=spec["aspect_ratio"],
            ass_path=ass_path,
        )

        # Run FFmpeg
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="replace")[:500]
            await _fail_export(db, export, job, f"FFmpeg failed: {error_msg}", str(job.id))
            return

        # Verify output
        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            await _fail_export(db, export, job, "FFmpeg produced no output", str(job.id))
            return

        # Sanity check: output should not be excessively large
        input_size = os.path.getsize(input_path)
        output_size = os.path.getsize(output_path)
        if output_size > input_size * 2:
            await _fail_export(
                db, export, job,
                f"Output file suspiciously large ({output_size} bytes vs {input_size} input)",
                str(job.id),
            )
            # Delete the oversized output
            os.unlink(output_path)
            return

        # Update context with output path
        job.render_context = {**ctx_data, "output_path": output_path}
        await db.commit()

        # Enqueue next step
        from arq import create_pool
        from arq.connections import RedisSettings

        pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        await pool.enqueue_job("upload_output_task", export_id)
        await pool.close()

    except Exception as e:
        try:
            export_result = await db.execute(select(Export).where(Export.id == UUID(export_id)))
            export = export_result.scalar_one_or_none()
            job_result = await db.execute(select(Job).where(Job.id == export.job_id)) if export else None
            job = job_result.scalar_one_or_none() if job_result else None
            if export and job:
                await _fail_export(db, export, job, str(e), str(job.id))
        except Exception:
            pass
        raise
    finally:
        await db.close()


async def upload_output_task(ctx, export_id: str):
    """Step 3: Upload rendered file to S3, update DB, generate download URL, cleanup."""
    db = await _get_db_session()
    job_id_str = None
    try:
        exp_uuid = UUID(export_id)

        export_result = await db.execute(select(Export).where(Export.id == exp_uuid))
        export = export_result.scalar_one_or_none()
        if not export:
            return

        job_result = await db.execute(select(Job).where(Job.id == export.job_id))
        job = job_result.scalar_one_or_none()
        if not job or not job.render_context:
            return

        job_id_str = str(job.id)
        ctx_data = job.render_context
        output_path = ctx_data.get("output_path")

        if not output_path or not os.path.exists(output_path):
            await _fail_export(db, export, job, "Rendered output file not found", job_id_str)
            return

        # Upload to S3
        s3_key = f"renders/{export.user_id}/{export.id}.mp4"
        await upload_file_to_s3(output_path, s3_key)

        # Generate presigned download URL (1 hour)
        download_url = generate_presigned_url(s3_key, expires_in=3600)

        # Update export
        export.s3_key = s3_key
        export.download_url = download_url
        export.expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        export.status = "rendered"

        # Update job
        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)

        await db.commit()

        # Cleanup temp files
        _cleanup_temp_dir(job_id_str)

    except Exception as e:
        try:
            export_result = await db.execute(select(Export).where(Export.id == UUID(export_id)))
            export = export_result.scalar_one_or_none()
            job_result = await db.execute(select(Job).where(Job.id == export.job_id)) if export else None
            job = job_result.scalar_one_or_none() if job_result else None
            if export and job:
                await _fail_export(db, export, job, str(e), str(job.id) if job else "unknown")
        except Exception:
            pass
        if job_id_str:
            _cleanup_temp_dir(job_id_str)
        raise
    finally:
        await db.close()
