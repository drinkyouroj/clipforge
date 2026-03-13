import io
from unittest.mock import patch, AsyncMock

import pytest


@pytest.fixture
async def auth_client(client):
    """Client that is logged in."""
    await client.post("/auth/register", json={
        "email": "uploader@example.com",
        "password": "StrongPass123!",
        "tos_accepted": True,
    })
    await client.post("/auth/login", json={
        "email": "uploader@example.com",
        "password": "StrongPass123!",
    })
    return client


async def test_upload_unauthenticated(client):
    resp = await client.post("/videos/upload", files={"file": ("test.mp4", b"data", "video/mp4")})
    assert resp.status_code == 401


@patch("app.videos.service.upload_file_to_s3", new_callable=AsyncMock)
@patch("app.videos.service.validate_with_ffprobe")
@patch("app.videos.service.validate_magic_bytes")
async def test_upload_valid_video(mock_magic, mock_ffprobe, mock_s3, auth_client):
    mock_magic.return_value = True
    mock_ffprobe.return_value = {"duration": 120.0, "file_size": 1024, "streams": []}
    mock_s3.return_value = None

    resp = await auth_client.post(
        "/videos/upload",
        files={"file": ("test.mp4", b"x" * 100, "video/mp4")},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["original_filename"] == "test.mp4"
    assert data["status"] == "uploaded"


@patch("app.videos.service.validate_magic_bytes")
async def test_upload_invalid_type(mock_magic, auth_client):
    mock_magic.return_value = False

    resp = await auth_client.post(
        "/videos/upload",
        files={"file": ("test.txt", b"not a video", "text/plain")},
    )
    assert resp.status_code == 415


async def test_list_videos_empty(auth_client):
    resp = await auth_client.get("/videos/")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@patch("app.videos.service.upload_file_to_s3", new_callable=AsyncMock)
@patch("app.videos.service.validate_with_ffprobe")
@patch("app.videos.service.validate_magic_bytes")
async def test_list_my_videos(mock_magic, mock_ffprobe, mock_s3, auth_client):
    mock_magic.return_value = True
    mock_ffprobe.return_value = {"duration": 60.0, "file_size": 512, "streams": []}
    mock_s3.return_value = None

    await auth_client.post(
        "/videos/upload",
        files={"file": ("vid1.mp4", b"x" * 50, "video/mp4")},
    )
    resp = await auth_client.get("/videos/")
    assert resp.status_code == 200
    assert resp.json()["total"] == 1
