"""Tests for FFmpeg command assembly."""

from app.rendering.ffmpeg_cmd import build_ffmpeg_command


def test_basic_9_16_command():
    cmd = build_ffmpeg_command(
        input_path="/tmp/input.mp4",
        output_path="/tmp/output.mp4",
        start_time=10.0,
        duration=30.0,
        crop={"crop_w": 607, "crop_h": 1080, "crop_x": 200, "crop_y": 0},
        width=1080, height=1920,
        aspect_ratio="9:16",
        ass_path="/tmp/captions.ass",
    )
    assert cmd[0] == "ffmpeg"
    assert "-ss" in cmd
    assert "10.0" in cmd or "10" in cmd
    assert "-t" in cmd
    assert "-r" in cmd  # FPS flag
    assert "30" in cmd
    assert "-movflags" in cmd
    assert "+faststart" in cmd
    assert "-y" in cmd
    assert "/tmp/output.mp4" == cmd[-1]


def test_video_filter_chain_with_crop():
    cmd = build_ffmpeg_command(
        input_path="/tmp/input.mp4",
        output_path="/tmp/output.mp4",
        start_time=0.0, duration=30.0,
        crop={"crop_w": 607, "crop_h": 1080, "crop_x": 200, "crop_y": 0},
        width=1080, height=1920,
        aspect_ratio="9:16",
        ass_path="/tmp/captions.ass",
    )
    # Find the -vf argument
    vf_idx = cmd.index("-vf")
    vf_value = cmd[vf_idx + 1]
    assert "crop=607:1080:200:0" in vf_value
    assert "scale=1080:1920" in vf_value
    assert "ass=/tmp/captions.ass" in vf_value


def test_16_9_no_crop():
    """16:9 should not include crop filter (full frame)."""
    cmd = build_ffmpeg_command(
        input_path="/tmp/input.mp4",
        output_path="/tmp/output.mp4",
        start_time=0.0, duration=30.0,
        crop={"crop_w": 1920, "crop_h": 1080, "crop_x": 0, "crop_y": 0},
        width=1280, height=720,
        aspect_ratio="16:9",
        ass_path="/tmp/captions.ass",
    )
    vf_idx = cmd.index("-vf")
    vf_value = cmd[vf_idx + 1]
    assert "crop=" not in vf_value
    assert "scale=1280:720" in vf_value


def test_audio_settings():
    cmd = build_ffmpeg_command(
        input_path="/tmp/input.mp4",
        output_path="/tmp/output.mp4",
        start_time=0.0, duration=30.0,
        crop={"crop_w": 607, "crop_h": 1080, "crop_x": 200, "crop_y": 0},
        width=1080, height=1920,
        aspect_ratio="9:16",
        ass_path="/tmp/captions.ass",
    )
    assert "-c:a" in cmd
    assert "aac" in cmd
    assert "-b:a" in cmd
    assert "192k" in cmd
    assert "-af" in cmd
    # Check loudnorm filter
    af_idx = cmd.index("-af")
    assert "loudnorm" in cmd[af_idx + 1]
    assert "I=-14" in cmd[af_idx + 1]


def test_no_captions():
    """Command without captions should omit ass filter."""
    cmd = build_ffmpeg_command(
        input_path="/tmp/input.mp4",
        output_path="/tmp/output.mp4",
        start_time=0.0, duration=30.0,
        crop={"crop_w": 607, "crop_h": 1080, "crop_x": 200, "crop_y": 0},
        width=1080, height=1920,
        aspect_ratio="9:16",
        ass_path=None,
    )
    vf_idx = cmd.index("-vf")
    vf_value = cmd[vf_idx + 1]
    assert "ass=" not in vf_value
