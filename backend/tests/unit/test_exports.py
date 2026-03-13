"""Tests for export API endpoints."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
import pytest_asyncio

from app.db.models import Clip, Export, Job, Transcript, User, Video


@pytest_asyncio.fixture
async def auth_client(client):
    """Client that is logged in."""
    await client.post("/auth/register", json={
        "email": "exportuser@example.com",
        "password": "StrongPass123!",
        "tos_accepted": True,
    })
    await client.post("/auth/login", json={
        "email": "exportuser@example.com",
        "password": "StrongPass123!",
    })
    return client


@pytest_asyncio.fixture
async def selected_clip(auth_client, db_session):
    """Create a video with a selected clip ready for export."""
    me_resp = await auth_client.get("/auth/me")
    user_id = me_resp.json()["id"]

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
        content="hello world test",
        word_timestamps=[
            {"word": "hello", "start": 10.0, "end": 10.5},
            {"word": "world", "start": 10.5, "end": 11.0},
        ],
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
        hook="Great hook",
        status="selected",
    )
    db_session.add(clip)
    await db_session.commit()
    await db_session.refresh(clip)
    return clip


async def test_create_export(auth_client, selected_clip):
    resp = await auth_client.post("/exports", json={
        "clip_id": str(selected_clip.id),
        "platform": "shorts",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["platform"] == "shorts"
    assert data["aspect_ratio"] == "9:16"
    assert data["resolution"] == "1080x1920"
    assert data["status"] == "pending"
    assert data["job_id"] is not None


async def test_create_export_square(auth_client, selected_clip):
    resp = await auth_client.post("/exports", json={
        "clip_id": str(selected_clip.id),
        "platform": "square",
    })
    assert resp.status_code == 200
    assert resp.json()["aspect_ratio"] == "1:1"
    assert resp.json()["resolution"] == "1080x1080"


async def test_create_export_invalid_platform(auth_client, selected_clip):
    resp = await auth_client.post("/exports", json={
        "clip_id": str(selected_clip.id),
        "platform": "myspace",
    })
    assert resp.status_code == 422  # Pydantic validation


async def test_create_export_clip_not_selected(auth_client, db_session, selected_clip):
    """Can only export clips with status 'selected'."""
    # Change clip back to candidate
    await auth_client.patch(f"/clips/{selected_clip.id}", json={"status": "candidate"})

    resp = await auth_client.post("/exports", json={
        "clip_id": str(selected_clip.id),
        "platform": "shorts",
    })
    assert resp.status_code == 400
    assert "selected" in resp.json()["detail"]


async def test_create_export_clip_not_found(auth_client):
    resp = await auth_client.post("/exports", json={
        "clip_id": str(uuid4()),
        "platform": "shorts",
    })
    assert resp.status_code == 404


async def test_create_export_long_clip_allowed(auth_client, db_session):
    """Clip longer than platform max is allowed — pipeline truncates via -t flag."""
    me_resp = await auth_client.get("/auth/me")
    user_id = me_resp.json()["id"]

    video = Video(
        user_id=user_id,
        original_filename="long.mp4",
        s3_key=f"uploads/{user_id}/long.mp4",
        file_size=2048,
        duration=600.0,
        status="ready",
    )
    db_session.add(video)
    await db_session.flush()

    transcript = Transcript(
        video_id=video.id, content="test", word_timestamps=[], language="en",
    )
    db_session.add(transcript)
    await db_session.flush()

    clip = Clip(
        video_id=video.id,
        transcript_id=transcript.id,
        start_time=0.0,
        end_time=120.0,
        duration=120.0,  # 2 minutes — exceeds shorts max (60s), but pipeline truncates
        status="selected",
    )
    db_session.add(clip)
    await db_session.commit()

    resp = await auth_client.post("/exports", json={
        "clip_id": str(clip.id),
        "platform": "shorts",
    })
    assert resp.status_code == 200  # Allowed — pipeline will truncate to 60s


async def test_get_export(auth_client, selected_clip):
    # Create export first
    create_resp = await auth_client.post("/exports", json={
        "clip_id": str(selected_clip.id),
        "platform": "tiktok",
    })
    export_id = create_resp.json()["id"]

    resp = await auth_client.get(f"/exports/{export_id}")
    assert resp.status_code == 200
    assert resp.json()["platform"] == "tiktok"


async def test_get_export_not_found(auth_client):
    resp = await auth_client.get(f"/exports/{uuid4()}")
    assert resp.status_code == 404


async def test_get_exports_for_clip(auth_client, selected_clip):
    # Create two exports for same clip
    await auth_client.post("/exports", json={
        "clip_id": str(selected_clip.id),
        "platform": "shorts",
    })
    await auth_client.post("/exports", json={
        "clip_id": str(selected_clip.id),
        "platform": "reels",
    })

    resp = await auth_client.get(f"/exports/clip/{selected_clip.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2


async def test_export_scoped_to_user(client, db_session, selected_clip):
    """Another user can't see exports."""
    await client.post("/auth/register", json={
        "email": "exportother@example.com",
        "password": "StrongPass123!",
        "tos_accepted": True,
    })
    await client.post("/auth/login", json={
        "email": "exportother@example.com",
        "password": "StrongPass123!",
    })

    resp = await client.get(f"/exports/clip/{selected_clip.id}")
    assert resp.status_code == 404


async def test_rate_limit_exports(auth_client, selected_clip, db_session):
    """Rate limit blocks after max exports per day."""
    me_resp = await auth_client.get("/auth/me")
    user_id = me_resp.json()["id"]

    # Insert 10 exports directly to hit rate limit
    for i in range(10):
        job = Job(
            user_id=user_id,
            video_id=selected_clip.video_id,
            job_type="render",
            status="completed",
        )
        db_session.add(job)
        await db_session.flush()

        exp = Export(
            clip_id=selected_clip.id,
            user_id=user_id,
            platform="shorts",
            aspect_ratio="9:16",
            resolution="1080x1920",
            status="rendered",
            job_id=job.id,
        )
        db_session.add(exp)
    await db_session.commit()

    resp = await auth_client.post("/exports", json={
        "clip_id": str(selected_clip.id),
        "platform": "shorts",
    })
    assert resp.status_code == 429
    assert "limit" in resp.json()["detail"].lower()
