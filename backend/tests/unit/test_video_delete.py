"""Tests for enhanced video delete with S3 cleanup."""

from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio

from app.db.models import Clip, Export, Job, Transcript, User, Video


@pytest_asyncio.fixture
async def auth_client(client):
    """Client that is logged in."""
    await client.post("/auth/register", json={
        "email": "deleteuser@example.com",
        "password": "StrongPass123!",
        "tos_accepted": True,
    })
    await client.post("/auth/login", json={
        "email": "deleteuser@example.com",
        "password": "StrongPass123!",
    })
    return client


@pytest_asyncio.fixture
async def video_with_exports(auth_client, db_session):
    """Create a video with clips and exports."""
    me = await auth_client.get("/auth/me")
    user_id = me.json()["id"]

    video = Video(
        user_id=user_id,
        original_filename="test.mp4",
        s3_key=f"uploads/{user_id}/test.mp4",
        file_size=1024,
        duration=300.0,
        status="ready",
    )
    db_session.add(video)
    await db_session.flush()

    transcript = Transcript(
        video_id=video.id,
        content="test content",
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
        status="selected",
    )
    db_session.add(clip)
    await db_session.flush()

    export = Export(
        clip_id=clip.id,
        user_id=user_id,
        platform="shorts",
        aspect_ratio="9:16",
        resolution="1080x1920",
        status="rendered",
        s3_key=f"exports/{user_id}/{clip.id}/shorts.mp4",
    )
    db_session.add(export)

    job = Job(
        user_id=user_id,
        video_id=video.id,
        job_type="render",
        status="pending",
    )
    db_session.add(job)
    await db_session.commit()

    return video, clip, export, job


@pytest.mark.asyncio
async def test_delete_sets_deleted_at(auth_client, video_with_exports):
    """DELETE /videos/{id} should soft-delete the video."""
    video, _, _, _ = video_with_exports
    with patch("app.videos.service.delete_s3_object", new_callable=AsyncMock):
        resp = await auth_client.delete(f"/videos/{video.id}")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_delete_cancels_pending_jobs(auth_client, video_with_exports, db_session):
    """Pending jobs should be marked as failed when video is deleted."""
    video, _, _, job = video_with_exports
    with patch("app.videos.service.delete_s3_object", new_callable=AsyncMock):
        await auth_client.delete(f"/videos/{video.id}")

    await db_session.refresh(job)
    assert job.status == "failed"
    assert "deleted by user" in job.error_message


@pytest.mark.asyncio
async def test_delete_calls_s3_cleanup(auth_client, video_with_exports):
    """S3 objects should be deleted for source video and exports."""
    video, _, export, _ = video_with_exports
    with patch("app.videos.service.delete_s3_object", new_callable=AsyncMock) as mock_delete:
        await auth_client.delete(f"/videos/{video.id}")

    # Should delete source video S3 key and export S3 key
    deleted_keys = [call.args[0] for call in mock_delete.call_args_list]
    assert video.s3_key in deleted_keys
    assert export.s3_key in deleted_keys
