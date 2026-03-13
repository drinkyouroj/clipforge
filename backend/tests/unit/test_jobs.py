from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db.models import Job, Video


@pytest.fixture
async def auth_client(client):
    """Client that is logged in."""
    await client.post("/auth/register", json={
        "email": "jobuser@example.com",
        "password": "StrongPass123!",
        "tos_accepted": True,
    })
    await client.post("/auth/login", json={
        "email": "jobuser@example.com",
        "password": "StrongPass123!",
    })
    return client


@pytest.fixture
async def video_with_job(auth_client, db_session):
    """Create a video and job in DB for testing."""
    # Get the user
    me_resp = await auth_client.get("/auth/me")
    user_id = me_resp.json()["id"]

    # Create a video directly in DB
    video = Video(
        user_id=user_id,
        original_filename="test.mp4",
        s3_key=f"uploads/{user_id}/test.mp4",
        file_size=1024,
        duration=60.0,
        status="uploaded",
    )
    db_session.add(video)
    await db_session.flush()

    # Create a job for the video
    job = Job(
        user_id=user_id,
        video_id=video.id,
        job_type="transcribe",
        status="pending",
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(video)
    await db_session.refresh(job)

    return video, job


async def test_get_job_status(auth_client, video_with_job):
    video, job = video_with_job
    resp = await auth_client.get(f"/jobs/{job.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_type"] == "transcribe"
    assert data["status"] == "pending"


async def test_job_not_found(auth_client):
    resp = await auth_client.get(f"/jobs/{uuid4()}")
    assert resp.status_code == 404


async def test_job_scoped_to_user(client, db_session, video_with_job):
    """A different user cannot see another user's job."""
    _, job = video_with_job

    # Register and login as a different user
    await client.post("/auth/register", json={
        "email": "other@example.com",
        "password": "StrongPass123!",
        "tos_accepted": True,
    })
    await client.post("/auth/login", json={
        "email": "other@example.com",
        "password": "StrongPass123!",
    })

    resp = await client.get(f"/jobs/{job.id}")
    assert resp.status_code == 404


async def test_get_jobs_for_video(auth_client, video_with_job):
    video, job = video_with_job
    resp = await auth_client.get(f"/jobs/video/{video.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == str(job.id)


async def test_get_jobs_for_video_empty(auth_client, video_with_job):
    resp = await auth_client.get(f"/jobs/video/{uuid4()}")
    assert resp.status_code == 200
    assert resp.json() == []
