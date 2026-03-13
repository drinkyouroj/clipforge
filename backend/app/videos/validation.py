import json
import subprocess

import filetype

ALLOWED_MIME_TYPES = {
    "video/mp4",
    "video/quicktime",
    "video/x-msvideo",
    "video/x-matroska",
    "video/webm",
}

MAX_DURATION = 10800  # 3 hours in seconds


def validate_magic_bytes(file_path: str) -> bool:
    try:
        kind = filetype.guess(file_path)
        if kind is None:
            return False
        return kind.mime in ALLOWED_MIME_TYPES
    except Exception:
        return False


def validate_with_ffprobe(file_path: str) -> dict | None:
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format", "-show_streams",
                file_path,
            ],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return None
        probe = json.loads(result.stdout)
        streams = probe.get("streams", [])
        has_video = any(s.get("codec_type") == "video" for s in streams)
        has_audio = any(s.get("codec_type") == "audio" for s in streams)
        if not has_video or not has_audio:
            return None
        duration = float(probe["format"].get("duration", 0))
        if duration > MAX_DURATION:
            return None
        return {
            "duration": duration,
            "file_size": int(probe["format"].get("size", 0)),
            "streams": streams,
        }
    except Exception:
        return None
