"""Tests for platform export specifications."""

from app.rendering.specs import get_platform_spec, PLATFORMS


def test_all_five_platforms_defined():
    assert set(PLATFORMS.keys()) == {"shorts", "tiktok", "reels", "square", "twitter"}


def test_shorts_spec():
    spec = get_platform_spec("shorts")
    assert spec["aspect_ratio"] == "9:16"
    assert spec["width"] == 1080
    assert spec["height"] == 1920
    assert spec["fps"] == 30
    assert spec["max_duration"] == 60


def test_square_spec():
    spec = get_platform_spec("square")
    assert spec["aspect_ratio"] == "1:1"
    assert spec["width"] == 1080
    assert spec["height"] == 1080


def test_twitter_spec():
    spec = get_platform_spec("twitter")
    assert spec["aspect_ratio"] == "16:9"
    assert spec["width"] == 1280
    assert spec["height"] == 720
    assert spec["max_duration"] == 140


def test_all_specs_have_required_fields():
    required = {"aspect_ratio", "width", "height", "fps", "max_duration", "codec", "audio_bitrate"}
    for key, spec in PLATFORMS.items():
        for field in required:
            assert field in spec, f"Platform '{key}' missing field '{field}'"


def test_invalid_platform_raises():
    import pytest
    with pytest.raises(ValueError, match="Unknown platform"):
        get_platform_spec("myspace")
