"""FFmpeg command assembly for clip rendering."""


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

    # Captions
    if ass_path:
        vf_parts.append(f"ass={ass_path}")

    vf_chain = ",".join(vf_parts)

    cmd = [
        "ffmpeg",
        "-ss", str(start_time),
        "-i", input_path,
        "-t", str(duration),
        "-vf", vf_chain,
        "-r", str(fps),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ac", "2",
        "-af", "loudnorm=I=-14:LRA=11:TP=-1.5",
        "-movflags", "+faststart",
        "-y",
        output_path,
    ]

    return cmd
