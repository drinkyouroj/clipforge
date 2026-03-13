"""Tests for clip detection post-processing (scorer.py)."""

from app.clip_detection.scorer import (
    clean_json_response,
    parse_clip_response,
    validate_clips,
    dedup_clips,
)


def test_clean_json_strips_markdown_fences():
    raw = '```json\n{"clips": []}\n```'
    assert clean_json_response(raw) == '{"clips": []}'


def test_clean_json_strips_trailing_commas():
    raw = '{"clips": [{"a": 1,},],}'
    cleaned = clean_json_response(raw)
    assert ",}" not in cleaned
    assert ",]" not in cleaned


def test_parse_clip_response_valid_json():
    raw = '{"clips": [], "total_candidates": 0, "video_summary": "test"}'
    result = parse_clip_response(raw)
    assert result["total_candidates"] == 0


def test_parse_clip_response_with_fences():
    raw = '```json\n{"clips": [], "total_candidates": 0}\n```'
    result = parse_clip_response(raw)
    assert result["total_candidates"] == 0


def test_validate_clips_removes_invalid():
    clips = [
        {"start_time": 10.0, "end_time": 50.0, "duration": 40.0, "virality_score": 80},
        {"start_time": -5.0, "end_time": 20.0, "duration": 25.0},  # negative start
        {"start_time": 100.0, "end_time": 90.0, "duration": -10.0},  # end < start
        {"start_time": 0.0, "end_time": 500.0, "duration": 500.0},  # exceeds video duration
        {"start_time": 0.0, "end_time": 5.0, "duration": 5.0},  # too short (< 15s)
    ]
    valid = validate_clips(clips, video_duration=120.0)
    assert len(valid) == 1
    assert valid[0]["start_time"] == 10.0


def test_validate_clips_recalculates_duration():
    clips = [
        {"start_time": 10.0, "end_time": 50.0, "duration": 999.0, "virality_score": 80},
    ]
    valid = validate_clips(clips, video_duration=120.0)
    assert valid[0]["duration"] == 40.0  # recalculated, not 999


def test_validate_clips_clamps_score():
    clips = [
        {"start_time": 0.0, "end_time": 30.0, "duration": 30.0, "virality_score": 150},
    ]
    valid = validate_clips(clips, video_duration=120.0)
    assert valid[0]["virality_score"] == 100


def test_validate_clips_allows_1s_tolerance():
    """Clip ending 0.5s past video duration should be accepted."""
    clips = [
        {"start_time": 90.0, "end_time": 120.5, "duration": 30.5, "virality_score": 70},
    ]
    valid = validate_clips(clips, video_duration=120.0)
    assert len(valid) == 1


def test_dedup_removes_overlapping_clips():
    clips = [
        {"start_time": 0.0, "end_time": 40.0, "duration": 40.0, "virality_score": 90},
        {"start_time": 5.0, "end_time": 45.0, "duration": 40.0, "virality_score": 70},  # >50% overlap
    ]
    deduped = dedup_clips(clips)
    assert len(deduped) == 1
    assert deduped[0]["virality_score"] == 90  # keeps higher score


def test_dedup_keeps_non_overlapping():
    clips = [
        {"start_time": 0.0, "end_time": 30.0, "duration": 30.0, "virality_score": 80},
        {"start_time": 60.0, "end_time": 90.0, "duration": 30.0, "virality_score": 75},
    ]
    deduped = dedup_clips(clips)
    assert len(deduped) == 2


def test_dedup_handles_empty():
    assert dedup_clips([]) == []
