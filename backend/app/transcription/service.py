import os
import time

import openai

from app.config import settings
from app.transcription.audio import extract_audio, split_audio

MAX_WHISPER_FILE_SIZE = 24 * 1024 * 1024  # 24MB (headroom below 25MB limit)
MAX_RETRIES = 3


async def transcribe_audio(audio_path: str) -> dict:
    """Send audio to Whisper API, return transcript with word timestamps.

    Handles files > 24MB by chunking per DECISION_004.
    """
    file_size = os.path.getsize(audio_path)
    if file_size <= MAX_WHISPER_FILE_SIZE:
        return await _transcribe_single(audio_path)
    else:
        return await _transcribe_chunked(audio_path)


async def _transcribe_single(audio_path: str) -> dict:
    """Transcribe a single audio file via Whisper API."""
    client = openai.AsyncOpenAI(api_key=settings.openai_api_key)

    for attempt in range(MAX_RETRIES):
        try:
            with open(audio_path, "rb") as f:
                response = await client.audio.transcriptions.create(
                    model="whisper-1",
                    file=f,
                    response_format="verbose_json",
                    timestamp_granularities=["word"],
                )
            return {
                "text": response.text,
                "words": [
                    {"word": w.word, "start": w.start, "end": w.end}
                    for w in (response.words or [])
                ],
                "language": getattr(response, "language", "en"),
            }
        except Exception:
            if attempt == MAX_RETRIES - 1:
                raise
            time.sleep(2 ** (attempt + 1))  # 2s, 4s, 8s backoff


async def _transcribe_chunked(audio_path: str) -> dict:
    """Split audio into chunks, transcribe each, merge with offset correction.

    Per DECISION_004: trim 2.5s from each side of chunk boundaries.
    """
    chunk_dir = os.path.dirname(audio_path)
    chunks = split_audio(audio_path, chunk_dir)

    all_text = []
    all_words = []
    cumulative_offset = 0.0
    trim_seconds = 2.5  # Per DECISION_004

    for i, chunk_path in enumerate(chunks):
        try:
            result = await _transcribe_single(chunk_path)

            words = result.get("words", [])

            if i > 0 and words:
                # Trim first 2.5s of this chunk's words (overlap region)
                words = [w for w in words if w["start"] >= trim_seconds]

            if i < len(chunks) - 1 and words:
                # Trim last 2.5s of this chunk's words (overlap region)
                max_time = max(w["end"] for w in words) if words else 0
                words = [w for w in words if w["end"] <= max_time - trim_seconds]

            # Offset timestamps by cumulative duration
            for w in words:
                w["start"] += cumulative_offset
                w["end"] += cumulative_offset

            all_words.extend(words)
            all_text.append(result.get("text", ""))

            # Get chunk duration for offset calculation
            import subprocess
            import json
            probe_result = subprocess.run(
                [
                    "ffprobe", "-v", "quiet",
                    "-print_format", "json",
                    "-show_format", chunk_path,
                ],
                capture_output=True, text=True, timeout=30,
            )
            probe = json.loads(probe_result.stdout)
            chunk_duration = float(probe["format"]["duration"])
            # Subtract overlap from offset (2.5s trimmed from each side)
            cumulative_offset += chunk_duration - (trim_seconds if i > 0 else 0)
        finally:
            # Clean up chunk file
            if os.path.exists(chunk_path):
                os.unlink(chunk_path)

    return {
        "text": " ".join(all_text),
        "words": all_words,
        "language": "en",
    }
