import os
import subprocess


def extract_audio(video_path: str, output_path: str) -> str:
    """Extract audio from video as mono 16kHz WAV for Whisper.

    Uses WAV (pcm_s16le) to avoid dependency on libmp3lame encoder.
    """
    result = subprocess.run(
        [
            "ffmpeg", "-i", video_path,
            "-vn", "-ac", "1", "-ar", "16000",
            "-c:a", "pcm_s16le",
            "-y", output_path,
        ],
        capture_output=True, timeout=600,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace") if result.stderr else ""
        raise RuntimeError(f"Audio extraction failed (exit {result.returncode}):\n{stderr}")
    if not os.path.exists(output_path):
        raise RuntimeError(f"Audio extraction failed: {output_path} not created")
    return output_path


def split_audio(audio_path: str, output_dir: str, chunk_duration: int = 3000) -> list[str]:
    """Split audio into chunks of chunk_duration seconds.

    Returns list of chunk file paths.
    """
    chunks = []
    offset = 0
    chunk_index = 0

    # Get audio duration via ffprobe
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_format", audio_path,
        ],
        capture_output=True, text=True, timeout=30,
    )
    import json
    probe = json.loads(result.stdout)
    total_duration = float(probe["format"]["duration"])

    while offset < total_duration:
        chunk_path = os.path.join(output_dir, f"chunk_{chunk_index:03d}.wav")
        # Add 5s overlap (2.5s each side per DECISION_004)
        start = max(0, offset - 5) if chunk_index > 0 else 0
        duration = chunk_duration + (5 if chunk_index > 0 else 0)

        subprocess.run(
            [
                "ffmpeg", "-i", audio_path,
                "-ss", str(offset),
                "-t", str(chunk_duration),
                "-c:a", "pcm_s16le",
                "-y", chunk_path,
            ],
            capture_output=True, check=True, timeout=120,
        )
        chunks.append(chunk_path)
        offset += chunk_duration
        chunk_index += 1

    return chunks
