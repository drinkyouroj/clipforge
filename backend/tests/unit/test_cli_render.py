"""Tests for CLI local rendering pipeline."""

from unittest.mock import patch, MagicMock
import tempfile
import os


def test_render_clip_local_builds_correct_command(tmp_path):
    """Test render_clip_local assembles the right FFmpeg command."""
    from app.cli import render_clip_local

    mock_face_track = {"frames": [{"t": 0, "x": 500, "y": 300}], "smoothed": True, "method": "mediapipe"}
    output_path = str(tmp_path / "output" / "clip.mp4")

    with patch("app.cli.build_face_track", return_value=mock_face_track) as mock_build, \
         patch("subprocess.run") as mock_run, \
         patch("app.rendering.ffmpeg_cmd.build_ffmpeg_command", return_value=["ffmpeg", "-fake"]) as mock_cmd:

        mock_run.return_value = MagicMock(returncode=0)

        result = render_clip_local(
            video_path="/fake/video.mp4",
            start_time=10.0,
            end_time=40.0,
            platform="shorts",
            output_path=output_path,
            word_timestamps=[{"word": "test", "start": 10.0, "end": 10.5}],
            no_captions=False,
            face_track=None,  # should trigger face detection
            tmp_dir=str(tmp_path),
            video_width=1920,
            video_height=1080,
        )

    assert result["face_track"] == mock_face_track
    mock_build.assert_called_once()
    assert mock_run.called


def test_render_clip_local_reuses_face_track(tmp_path):
    """Test that passing face_track skips face detection."""
    from app.cli import render_clip_local

    existing_track = {"frames": [{"t": 0, "x": 500, "y": 300}], "smoothed": True, "method": "mediapipe"}
    output_path = str(tmp_path / "output" / "clip.mp4")

    with patch("app.cli.build_face_track") as mock_build, \
         patch("subprocess.run") as mock_run, \
         patch("app.rendering.ffmpeg_cmd.build_ffmpeg_command", return_value=["ffmpeg", "-fake"]):

        mock_run.return_value = MagicMock(returncode=0)

        render_clip_local(
            video_path="/fake/video.mp4",
            start_time=10.0,
            end_time=40.0,
            platform="shorts",
            output_path=output_path,
            word_timestamps=[],
            no_captions=True,
            face_track=existing_track,  # pre-computed
            tmp_dir=str(tmp_path),
            video_width=1920,
            video_height=1080,
        )

    mock_build.assert_not_called()
