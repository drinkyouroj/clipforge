from unittest.mock import patch, MagicMock, AsyncMock
from uuid import uuid4

import pytest

import app.transcription.service  # ensure module is loaded for patching
from app.db.models import Transcript, Video


def test_extract_audio_generates_ffmpeg_command():
    """Verify FFmpeg is called with correct args for audio extraction."""
    with patch("app.transcription.audio.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        with patch("app.transcription.audio.os.path.exists", return_value=True):
            from app.transcription.audio import extract_audio
            output = extract_audio("/input/video.mp4", "/output/audio.mp3")
            assert output == "/output/audio.mp3"
            cmd = mock_run.call_args[0][0]
            assert cmd[0] == "ffmpeg"
            assert "-vn" in cmd  # no video
            assert "-ac" in cmd  # mono
            assert "1" in cmd


async def test_transcribe_single_calls_whisper():
    """Verify Whisper API is called and response is parsed."""
    mock_word = MagicMock()
    mock_word.word = "hello"
    mock_word.start = 0.0
    mock_word.end = 0.5

    mock_response = MagicMock()
    mock_response.text = "hello world"
    mock_response.words = [mock_word]
    mock_response.language = "en"

    mock_client = MagicMock()
    mock_client.audio.transcriptions.create = AsyncMock(return_value=mock_response)

    with patch("app.transcription.service.openai.AsyncOpenAI", return_value=mock_client):
        with patch("builtins.open", MagicMock()):
            from app.transcription.service import _transcribe_single
            result = await _transcribe_single("/path/to/audio.mp3")

    assert result["text"] == "hello world"
    assert len(result["words"]) == 1
    assert result["words"][0]["word"] == "hello"
    assert result["language"] == "en"


@patch("app.transcription.service.os.path.getsize", return_value=1000)
@patch("app.transcription.service._transcribe_single", new_callable=AsyncMock)
async def test_transcribe_audio_small_file(mock_single, mock_size):
    """Files under 24MB use single transcription."""
    mock_single.return_value = {"text": "test", "words": [], "language": "en"}
    from app.transcription.service import transcribe_audio
    result = await transcribe_audio("/path/to/audio.mp3")
    mock_single.assert_called_once_with("/path/to/audio.mp3")
    assert result["text"] == "test"


@pytest.fixture
async def auth_client(client):
    """Client that is logged in."""
    await client.post("/auth/register", json={
        "email": "transcriptuser@example.com",
        "password": "StrongPass123!",
        "tos_accepted": True,
    })
    await client.post("/auth/login", json={
        "email": "transcriptuser@example.com",
        "password": "StrongPass123!",
    })
    return client


async def test_get_transcript(auth_client, db_session):
    """Test getting a transcript for a video."""
    me_resp = await auth_client.get("/auth/me")
    user_id = me_resp.json()["id"]

    # Create video
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

    # Create transcript
    transcript = Transcript(
        video_id=video.id,
        content="hello world this is a test",
        word_timestamps=[
            {"word": "hello", "start": 0.0, "end": 0.5},
            {"word": "world", "start": 0.5, "end": 1.0},
        ],
        language="en",
    )
    db_session.add(transcript)
    await db_session.commit()

    resp = await auth_client.get(f"/transcripts/{video.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["content"] == "hello world this is a test"
    assert len(data["word_timestamps"]) == 2


async def test_get_transcript_not_found(auth_client):
    """Test 404 when transcript doesn't exist."""
    resp = await auth_client.get(f"/transcripts/{uuid4()}")
    assert resp.status_code == 404


async def test_get_transcript_scoped_to_user(client, db_session, auth_client):
    """Another user can't access transcript."""
    me_resp = await auth_client.get("/auth/me")
    user_id = me_resp.json()["id"]

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

    transcript = Transcript(
        video_id=video.id,
        content="secret transcript",
        language="en",
    )
    db_session.add(transcript)
    await db_session.commit()

    # Register and login as different user
    await client.post("/auth/register", json={
        "email": "other2@example.com",
        "password": "StrongPass123!",
        "tos_accepted": True,
    })
    await client.post("/auth/login", json={
        "email": "other2@example.com",
        "password": "StrongPass123!",
    })

    resp = await client.get(f"/transcripts/{video.id}")
    assert resp.status_code == 404
