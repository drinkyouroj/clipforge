"""FFmpeg command assembly for clip rendering."""

import subprocess

_h264_encoder = None
_ass_filter_available = None


def get_h264_encoder() -> tuple[str, list[str]]:
    """Detect the best available H264 encoder.

    Returns (encoder_name, extra_flags) tuple.
    """
    global _h264_encoder
    if _h264_encoder is not None:
        return _h264_encoder

    # Check available encoders
    try:
        result = subprocess.run(
            ["ffmpeg", "-encoders", "-hide_banner"],
            capture_output=True, text=True, timeout=5,
        )
        encoders = result.stdout
    except Exception:
        encoders = ""

    if "libx264" in encoders:
        _h264_encoder = ("libx264", ["-preset", "fast", "-crf", "23"])
    elif "h264_videotoolbox" in encoders:
        _h264_encoder = ("h264_videotoolbox", ["-q:v", "65"])
    elif "h264_nvenc" in encoders:
        _h264_encoder = ("h264_nvenc", ["-preset", "fast", "-cq", "23"])
    elif "h264_vaapi" in encoders:
        _h264_encoder = ("h264_vaapi", [])
    else:
        # Fallback: let FFmpeg pick its default H264 encoder
        _h264_encoder = ("libx264", ["-crf", "23"])

    return _h264_encoder


def has_ass_filter() -> bool:
    """Check if FFmpeg has the ass subtitle filter (requires libass)."""
    global _ass_filter_available
    if _ass_filter_available is not None:
        return _ass_filter_available

    try:
        result = subprocess.run(
            ["ffmpeg", "-filters", "-hide_banner"],
            capture_output=True, text=True, timeout=5,
        )
        _ass_filter_available = " ass " in result.stdout
    except Exception:
        _ass_filter_available = False

    return _ass_filter_available


def build_ffmpeg_command(
    input_path: str,
    output_path: str,
    start_time: float,
    duration: float,
    crop: dict,
    width: int,
    height: int,
    fps: int = 30,
    aspect_ratio: str = "9:16",
    ass_path: str | None = None,
) -> list[str]:
    """Build FFmpeg command for rendering a clip.

    Args:
        input_path: Path to input video file
        output_path: Path for output MP4
        start_time: Seek position in input video (seconds)
        duration: Clip duration (seconds)
        crop: Dict with crop_w, crop_h, crop_x, crop_y
        width: Target output width
        height: Target output height
        fps: Target output FPS (default 30)
        aspect_ratio: Target aspect ratio (used to detect 16:9 no-crop case)
        ass_path: Path to ASS subtitle file (None to skip captions)

    Returns:
        FFmpeg command as list of strings for subprocess
    """
    # Video filter chain
    vf_parts = []

    # Crop — skip for 16:9 (full frame passthrough, just scale)
    if aspect_ratio != "16:9":
        vf_parts.append(
            f"crop={crop['crop_w']}:{crop['crop_h']}:{crop['crop_x']}:{crop['crop_y']}"
        )

    # Scale to target resolution
    vf_parts.append(f"scale={width}:{height}")

    # Captions (requires libass)
    if ass_path and has_ass_filter():
        vf_parts.append(f"ass={ass_path}")

    vf_chain = ",".join(vf_parts)

    encoder, encoder_flags = get_h264_encoder()

    cmd = [
        "ffmpeg",
        "-ss", str(start_time),
        "-i", input_path,
        "-t", str(duration),
        "-vf", vf_chain,
        "-r", str(fps),
        "-c:v", encoder,
        *encoder_flags,
        "-c:a", "aac",
        "-b:a", "192k",
        "-ac", "2",
        "-af", "loudnorm=I=-14:LRA=11:TP=-1.5",
        "-movflags", "+faststart",
        "-y",
        output_path,
    ]

    return cmd
