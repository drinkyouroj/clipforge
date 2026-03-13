"""Tests for render pipeline model changes."""

from app.db.models import Clip, Export, Job


def test_clip_has_face_track_column():
    """Clip model has face_track JSONB column."""
    assert hasattr(Clip, "face_track")


def test_export_has_status_column():
    """Export model has status column with default."""
    assert hasattr(Export, "status")


def test_export_has_job_id_column():
    """Export model has job_id FK column."""
    assert hasattr(Export, "job_id")


def test_job_has_render_context_column():
    """Job model has render_context JSONB column."""
    assert hasattr(Job, "render_context")


async def test_create_export_with_status(db_session):
    """Can create an Export with status and job_id."""
    from app.db.models import User, Video, Transcript, Clip, Job, Export
    from datetime import datetime, timezone

    user = User(
        email="renderuser@example.com",
        hashed_password="hashed",
        tos_accepted_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    await db_session.flush()

    video = Video(
        user_id=user.id,
        original_filename="test.mp4",
        s3_key=f"uploads/{user.id}/test.mp4",
        file_size=1024,
        duration=300.0,
        status="ready",
    )
    db_session.add(video)
    await db_session.flush()

    transcript = Transcript(
        video_id=video.id,
        content="hello world",
        word_timestamps=[],
        language="en",
    )
    db_session.add(transcript)
    await db_session.flush()

    clip = Clip(
        video_id=video.id,
        transcript_id=transcript.id,
        start_time=10.0,
        end_time=50.0,
        duration=40.0,
        virality_score=85,
        status="selected",
        face_track={"frames": [{"t": 0.0, "x": 540, "y": 360}], "smoothed": True},
    )
    db_session.add(clip)
    await db_session.flush()

    job = Job(
        user_id=user.id,
        video_id=video.id,
        job_type="render",
        status="pending",
        render_context={"temp_dir": "/tmp/clipforge/render/test"},
    )
    db_session.add(job)
    await db_session.flush()

    export = Export(
        clip_id=clip.id,
        user_id=user.id,
        platform="shorts",
        aspect_ratio="9:16",
        resolution="1080x1920",
        status="pending",
        job_id=job.id,
    )
    db_session.add(export)
    await db_session.commit()
    await db_session.refresh(export)

    assert export.status == "pending"
    assert export.job_id == job.id
    assert clip.face_track["smoothed"] is True
    assert job.render_context["temp_dir"] == "/tmp/clipforge/render/test"
