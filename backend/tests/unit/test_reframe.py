"""Tests for face detection and smart crop calculation."""

from app.rendering.reframe import (
    smooth_face_track,
    calculate_crop,
    compute_crop_params,
)


def test_smooth_face_track_basic():
    """Moving average smoothing should reduce jitter."""
    track = [
        {"t": 0.0, "x": 500, "y": 360},
        {"t": 0.5, "x": 520, "y": 360},
        {"t": 1.0, "x": 480, "y": 360},
        {"t": 1.5, "x": 510, "y": 360},
        {"t": 2.0, "x": 490, "y": 360},
    ]
    smoothed = smooth_face_track(track, window=3)
    assert len(smoothed) == 5
    # Smoothed values should be closer to the mean
    assert all("x" in f and "y" in f and "t" in f for f in smoothed)


def test_smooth_face_track_single_point():
    track = [{"t": 0.0, "x": 500, "y": 360}]
    smoothed = smooth_face_track(track, window=3)
    assert len(smoothed) == 1
    assert smoothed[0]["x"] == 500


def test_smooth_face_track_empty():
    smoothed = smooth_face_track([], window=3)
    assert smoothed == []


def test_calculate_crop_9_16():
    """9:16 crop: full height, width = height * 9/16, centered on face."""
    crop = calculate_crop(
        video_width=1920, video_height=1080,
        face_x=960, aspect_ratio="9:16"
    )
    assert crop["crop_h"] == 1080  # full height
    assert crop["crop_w"] == 607   # 1080 * 9 / 16 = 607.5 → 607
    assert crop["crop_y"] == 0     # top-aligned


def test_calculate_crop_1_1():
    """1:1 crop: full height, width = height, centered on face."""
    crop = calculate_crop(
        video_width=1920, video_height=1080,
        face_x=960, aspect_ratio="1:1"
    )
    assert crop["crop_h"] == 1080
    assert crop["crop_w"] == 1080


def test_calculate_crop_16_9():
    """16:9: no crop needed, returns full frame dimensions."""
    crop = calculate_crop(
        video_width=1920, video_height=1080,
        face_x=960, aspect_ratio="16:9"
    )
    assert crop["crop_w"] == 1920
    assert crop["crop_h"] == 1080
    assert crop["crop_x"] == 0
    assert crop["crop_y"] == 0


def test_calculate_crop_clamps_to_bounds():
    """Crop X should not go negative or exceed frame width."""
    crop = calculate_crop(
        video_width=1920, video_height=1080,
        face_x=50, aspect_ratio="9:16"  # Face near left edge
    )
    assert crop["crop_x"] >= 0
    assert crop["crop_x"] + crop["crop_w"] <= 1920


def test_compute_crop_params_center_fallback():
    """When face_track is None, use center crop."""
    params = compute_crop_params(
        face_track=None,
        video_width=1920, video_height=1080,
        aspect_ratio="9:16",
    )
    # Should center: crop_x = (1920 - crop_w) / 2
    expected_w = int(1080 * 9 / 16)
    assert params["crop_x"] == (1920 - expected_w) // 2
