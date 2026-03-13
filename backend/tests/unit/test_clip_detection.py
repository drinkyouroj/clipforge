"""Tests for clip detection API endpoints and detector."""

from unittest.mock import patch, MagicMock, AsyncMock
from uuid import uuid4

import pytest

from app.db.models import Clip, Transcript, Video


@pytest.fixture
async def auth_client(client):
    """Client that is logged in."""
    await client.post("/auth/register", json={
        "email": "clipuser@example.com",
        "password": "StrongPass123!",
        "tos_accepted": True,
    })
    await client.post("/auth/login", json={
        "email": "clipuser@example.com",
        "password": "StrongPass123!",
    })
    return client


@pytest.fixture
async def video_with_clips(auth_client, db_session):
    """Create a video with clip candidates."""
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
        content="hello world this is a test",
        word_timestamps=[],
        language="en",
    )
    db_session.add(transcript)
    await db_session.flush()

    clip1 = Clip(
        video_id=video.id,
        transcript_id=transcript.id,
        start_time=10.0,
        end_time=50.0,
        duration=40.0,
        virality_score=85,
        hook="This is the hook",
        reasoning="Strong opener with insight",
        clip_type="insight",
        suggested_title="Amazing Insight",
        platform_fit=["shorts", "tiktok"],
        status="candidate",
    )
    clip2 = Clip(
        video_id=video.id,
        transcript_id=transcript.id,
        start_time=120.0,
        end_time=180.0,
        duration=60.0,
        virality_score=72,
        hook="Another great moment",
        reasoning="Emotional story",
        clip_type="story",
        suggested_title="Heartfelt Story",
        platform_fit=["reels"],
        status="candidate",
    )
    db_session.add_all([clip1, clip2])
    await db_session.commit()
    await db_session.refresh(video)
    await db_session.refresh(clip1)
    await db_session.refresh(clip2)

    return video, [clip1, clip2]


async def test_get_clips_for_video(auth_client, video_with_clips):
    video, clips = video_with_clips
    resp = await auth_client.get(f"/clips/video/{video.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    # Should be ordered by virality_score desc
    assert data["clips"][0]["virality_score"] == 85
    assert data["clips"][1]["virality_score"] == 72


async def test_get_clips_empty_video(auth_client, db_session):
    me_resp = await auth_client.get("/auth/me")
    user_id = me_resp.json()["id"]

    video = Video(
        user_id=user_id,
        original_filename="empty.mp4",
        s3_key=f"uploads/{user_id}/empty.mp4",
        file_size=512,
        duration=60.0,
        status="ready",
    )
    db_session.add(video)
    await db_session.commit()

    resp = await auth_client.get(f"/clips/video/{video.id}")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


async def test_get_clips_video_not_found(auth_client):
    resp = await auth_client.get(f"/clips/video/{uuid4()}")
    assert resp.status_code == 404


async def test_get_single_clip(auth_client, video_with_clips):
    _, clips = video_with_clips
    resp = await auth_client.get(f"/clips/{clips[0].id}")
    assert resp.status_code == 200
    assert resp.json()["hook"] == "This is the hook"


async def test_get_clip_scoped_to_user(client, db_session, video_with_clips):
    """Another user can't access clips."""
    _, clips = video_with_clips

    await client.post("/auth/register", json={
        "email": "otherclip@example.com",
        "password": "StrongPass123!",
        "tos_accepted": True,
    })
    await client.post("/auth/login", json={
        "email": "otherclip@example.com",
        "password": "StrongPass123!",
    })

    resp = await client.get(f"/clips/{clips[0].id}")
    assert resp.status_code == 404


async def test_update_clip_boundaries(auth_client, video_with_clips):
    _, clips = video_with_clips
    resp = await auth_client.patch(
        f"/clips/{clips[0].id}",
        json={"start_time": 15.0, "end_time": 55.0},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["start_time"] == 15.0
    assert data["end_time"] == 55.0
    assert data["duration"] == 40.0


async def test_update_clip_status(auth_client, video_with_clips):
    _, clips = video_with_clips
    resp = await auth_client.patch(
        f"/clips/{clips[0].id}",
        json={"status": "selected"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "selected"


def test_format_transcript_with_timestamps():
    from app.clip_detection.detector import format_transcript_with_timestamps

    words = [
        {"word": "hello", "start": 0.0, "end": 0.5},
        {"word": "world", "start": 0.5, "end": 1.0},
    ]
    result = format_transcript_with_timestamps(words)
    assert "[00:00.0 - 00:01.0]" in result
    assert "hello world" in result


def test_format_transcript_empty():
    from app.clip_detection.detector import format_transcript_with_timestamps

    result = format_transcript_with_timestamps([])
    assert "No transcript" in result
