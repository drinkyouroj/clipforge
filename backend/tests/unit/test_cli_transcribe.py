"""Tests for CLI local transcription."""

from unittest.mock import patch, MagicMock


def test_transcribe_local_returns_expected_format():
    """Test that transcribe_local maps faster-whisper output to our dict format."""
    from app.cli import transcribe_local

    mock_segment = MagicMock()
    mock_segment.text = "Hello world this is a test"

    mock_word1 = MagicMock()
    mock_word1.start = 0.0
    mock_word1.end = 0.5
    mock_word1.word = "Hello"

    mock_word2 = MagicMock()
    mock_word2.start = 0.5
    mock_word2.end = 1.0
    mock_word2.word = "world"

    mock_segment.words = [mock_word1, mock_word2]

    mock_model = MagicMock()
    mock_model.transcribe.return_value = ([mock_segment], MagicMock(language="en"))

    with patch("app.cli.WhisperModel", return_value=mock_model):
        result = transcribe_local("/fake/audio.mp3", "base")

    assert "text" in result
    assert "words" in result
    assert len(result["words"]) == 2
    assert result["words"][0] == {"word": "Hello", "start": 0.0, "end": 0.5}
    assert result["words"][1] == {"word": "world", "start": 0.5, "end": 1.0}


def test_transcribe_local_empty_audio():
    """Test that empty transcription returns empty words list."""
    from app.cli import transcribe_local

    mock_model = MagicMock()
    mock_model.transcribe.return_value = ([], MagicMock(language="en"))

    with patch("app.cli.WhisperModel", return_value=mock_model):
        result = transcribe_local("/fake/audio.mp3", "base")

    assert result["text"] == ""
    assert result["words"] == []
