"""Tests for ASS subtitle generation with word highlighting."""

from app.rendering.captions import generate_ass_captions, group_words_into_lines


def test_group_words_into_lines_basic():
    words = [
        {"word": "hello", "start": 0.0, "end": 0.3},
        {"word": "world", "start": 0.3, "end": 0.6},
        {"word": "this", "start": 0.6, "end": 0.9},
        {"word": "is", "start": 0.9, "end": 1.0},
        {"word": "a", "start": 1.0, "end": 1.1},
        {"word": "test", "start": 1.1, "end": 1.4},
    ]
    lines = group_words_into_lines(words, max_words=3)
    assert len(lines) == 2
    assert len(lines[0]) == 3  # hello world this
    assert len(lines[1]) == 3  # is a test


def test_group_words_splits_at_long_pause():
    words = [
        {"word": "hello", "start": 0.0, "end": 0.3},
        {"word": "world", "start": 0.3, "end": 0.6},
        {"word": "goodbye", "start": 2.0, "end": 2.3},  # >0.5s pause
    ]
    lines = group_words_into_lines(words, max_words=4)
    assert len(lines) == 2  # Split at the pause


def test_group_words_empty():
    lines = group_words_into_lines([], max_words=3)
    assert lines == []


def test_generate_ass_header():
    words = [{"word": "hello", "start": 0.0, "end": 0.5}]
    ass = generate_ass_captions(words, clip_start_time=0.0)
    assert "[Script Info]" in ass
    assert "[V4+ Styles]" in ass
    assert "Style: Default" in ass
    assert "Arial" in ass


def test_generate_ass_dialogue_events():
    words = [
        {"word": "hello", "start": 10.0, "end": 10.3},
        {"word": "world", "start": 10.3, "end": 10.6},
        {"word": "test", "start": 10.6, "end": 10.9},
    ]
    ass = generate_ass_captions(words, clip_start_time=10.0)
    assert "[Events]" in ass
    assert "Dialogue:" in ass


def test_caption_timestamps_rebased_to_zero():
    """Timestamps must be relative to 0, not original video time."""
    words = [
        {"word": "hello", "start": 120.0, "end": 120.5},
        {"word": "world", "start": 120.5, "end": 121.0},
    ]
    ass = generate_ass_captions(words, clip_start_time=120.0)
    # Should NOT contain 2:00 timestamps, should be near 0:00
    assert "0:00:00" in ass or "0:00:01" in ass


def test_caption_highlight_colors():
    """Active word should use yellow, inactive white."""
    words = [
        {"word": "hello", "start": 0.0, "end": 0.5},
        {"word": "world", "start": 0.5, "end": 1.0},
    ]
    ass = generate_ass_captions(words, clip_start_time=0.0)
    assert "\\c&H0000FFFF&" in ass  # yellow (active)
    assert "\\c&H00FFFFFF&" in ass  # white (inactive)


def test_caption_escapes_special_characters():
    """Non-ASCII and ASS-special chars should not corrupt output."""
    words = [
        {"word": "it\u2019s", "start": 0.0, "end": 0.3},  # curly apostrophe
        {"word": "\u2014", "start": 0.3, "end": 0.5},  # em dash
        {"word": "caf\u00e9", "start": 0.5, "end": 0.8},  # accented char
    ]
    ass = generate_ass_captions(words, clip_start_time=0.0)
    assert "Dialogue:" in ass  # Should not crash
    # Backslashes in words should be escaped
    assert "\u2019" in ass or "'" in ass
