"""Tests for CLI local LLM clip detection."""

from unittest.mock import patch, MagicMock
import json


def test_detect_clips_local_parses_response():
    """Test that detect_clips_local calls LLM and parses JSON response."""
    from app.cli import detect_clips_local

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps({
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

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response

    with patch("app.cli.OpenAI", return_value=mock_client):
        result = detect_clips_local(
            transcript_text="Hello world test transcript with enough words",
            word_timestamps=[{"word": "Hello", "start": 0.0, "end": 0.5}] * 60,
            video_duration=120.0,
            llm_url="http://localhost:8080",
            llm_model="test-model",
        )

    assert len(result["clips"]) == 1
    assert result["clips"][0]["virality_score"] == 85
    assert result["clips"][0]["start_time"] == 10.0


def test_detect_clips_local_handles_bad_json():
    """Test that detect_clips_local retries on bad JSON."""
    from app.cli import detect_clips_local

    bad_response = MagicMock()
    bad_response.choices = [MagicMock()]
    bad_response.choices[0].message.content = "This is not JSON at all"

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = bad_response

    with patch("app.cli.OpenAI", return_value=mock_client):
        result = detect_clips_local(
            transcript_text="Test transcript",
            word_timestamps=[{"word": "test", "start": 0.0, "end": 0.5}] * 60,
            video_duration=120.0,
            llm_url="http://localhost:8080",
            llm_model="test-model",
        )

    # Should return empty clips after retries exhausted
    assert result["clips"] == []
    assert result["total_candidates"] == 0
