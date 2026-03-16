"""Tests for CLI clip detection via Anthropic API."""

from unittest.mock import patch, MagicMock
import json


def test_detect_clips_local_parses_response():
    """Test that detect_clips_local calls Anthropic and parses JSON response."""
    from app.cli import detect_clips_local

    mock_response = MagicMock()
    mock_text_block = MagicMock()
    mock_text_block.text = json.dumps({
        "clips": [
            {
                "start_time": 10.0,
                "end_time": 40.0,
                "duration": 30.0,
                "virality_score": 85,
                "hook": "This is amazing",
                "reasoning": "Great content",
                "clip_type": "insight",
                "suggested_title": "Amazing Insight",
                "platform_fit": ["shorts"],
            }
        ],
        "total_candidates": 1,
        "video_summary": "A test video",
    })
    mock_response.content = [mock_text_block]

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    with patch("app.cli.anthropic.Anthropic", return_value=mock_client):
        result = detect_clips_local(
            transcript_text="Hello world test transcript with enough words",
            word_timestamps=[{"word": "Hello", "start": 0.0, "end": 0.5}] * 60,
            video_duration=120.0,
        )

    assert len(result["clips"]) == 1
    assert result["clips"][0]["virality_score"] == 85
    assert result["clips"][0]["start_time"] == 10.0


def test_detect_clips_local_handles_bad_json():
    """Test that detect_clips_local retries on bad JSON."""
    from app.cli import detect_clips_local

    mock_response = MagicMock()
    mock_text_block = MagicMock()
    mock_text_block.text = "This is not JSON at all"
    mock_response.content = [mock_text_block]

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    with patch("app.cli.anthropic.Anthropic", return_value=mock_client):
        result = detect_clips_local(
            transcript_text="Test transcript",
            word_timestamps=[{"word": "test", "start": 0.0, "end": 0.5}] * 60,
            video_duration=120.0,
        )

    # Should return empty clips after retries exhausted
    assert result["clips"] == []
    assert result["total_candidates"] == 0
