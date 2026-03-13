import uuid
from unittest.mock import patch, MagicMock

from app.videos.storage import generate_s3_key, generate_presigned_url


def test_generate_s3_key_user_scoped():
    user_id = uuid.uuid4()
    key = generate_s3_key(user_id, "my_video.mp4")
    assert key.startswith(f"uploads/{user_id}/")
    assert key.endswith(".mp4")


def test_generate_s3_key_extracts_extension():
    user_id = uuid.uuid4()
    key = generate_s3_key(user_id, "recording.mov")
    assert key.endswith(".mov")


def test_generate_s3_key_default_extension():
    user_id = uuid.uuid4()
    key = generate_s3_key(user_id, "noextension")
    assert key.endswith(".mp4")


@patch("app.videos.storage.get_s3_client")
def test_generate_presigned_url_calls_boto3(mock_get_client):
    mock_client = MagicMock()
    mock_client.generate_presigned_url.return_value = "https://signed-url.example.com"
    mock_get_client.return_value = mock_client

    url = generate_presigned_url("uploads/123/video.mp4", expires_in=3600)
    assert url == "https://signed-url.example.com"
    mock_client.generate_presigned_url.assert_called_once()
