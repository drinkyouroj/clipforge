"""Main clip detection logic using Claude API."""

import os
from pathlib import Path

import anthropic

from app.config import settings
from app.clip_detection.scorer import parse_clip_response, validate_clips, dedup_clips

PROMPT_DIR = Path(__file__).parent / "prompts"
MAX_RETRIES = 2


def _load_prompt(version: str = "virality_v1") -> str:
    """Load a versioned prompt template from the prompts directory."""
    prompt_path = PROMPT_DIR / f"{version}.txt"
    return prompt_path.read_text()


def format_transcript_with_timestamps(words: list[dict]) -> str:
    """Format word-level timestamps into readable time-stamped segments.

    Groups words into ~30-second blocks for readability.
    """
    if not words:
        return "[No transcript available]"

    segments = []
    current_segment_words = []
    segment_start = words[0].get("start", 0.0)
    segment_duration = 30.0  # seconds per segment

    for word in words:
        current_segment_words.append(word.get("word", ""))
        word_end = word.get("end", 0.0)

        if word_end - segment_start >= segment_duration:
            start_fmt = _format_time(segment_start)
            end_fmt = _format_time(word_end)
            text = " ".join(current_segment_words)
            segments.append(f"[{start_fmt} - {end_fmt}] {text}")

            current_segment_words = []
            segment_start = word_end

    # Flush remaining words
    if current_segment_words:
        word_end = words[-1].get("end", segment_start)
        start_fmt = _format_time(segment_start)
        end_fmt = _format_time(word_end)
        text = " ".join(current_segment_words)
        segments.append(f"[{start_fmt} - {end_fmt}] {text}")

    return "\n".join(segments)


def _format_time(seconds: float) -> str:
    """Format seconds as MM:SS.S"""
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes:02d}:{secs:04.1f}"


def _format_duration(seconds: float) -> str:
    """Format seconds as human-readable duration."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    return f"{minutes}m {secs}s"


async def detect_clips(
    transcript_text: str,
    word_timestamps: list[dict],
    video_duration: float,
    prompt_version: str = "virality_v1",
) -> dict:
    """Run clip detection on a transcript using Claude API.

    Returns dict with 'clips', 'total_candidates', 'video_summary'.
    """
    # Format transcript with timestamps
    formatted_transcript = format_transcript_with_timestamps(word_timestamps)

    # Load and fill prompt template
    prompt_template = _load_prompt(prompt_version)
    prompt = prompt_template.replace("{transcript_text}", formatted_transcript)
    prompt = prompt.replace("{video_duration:.1f}", f"{video_duration:.1f}")
    prompt = prompt.replace("{video_duration_formatted}", _format_duration(video_duration))

    # Call Claude API with retries
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = await client.messages.create(
                model="claude-sonnet-4-5-20250514",
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )

            raw_text = response.content[0].text
            result = parse_clip_response(raw_text)

            # Validate and dedup
            clips = result.get("clips", [])
            clips = validate_clips(clips, video_duration)
            clips = dedup_clips(clips)

            return {
                "clips": clips,
                "total_candidates": len(clips),
                "video_summary": result.get("video_summary", ""),
            }

        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES:
                continue
            raise last_error


async def detect_clips_long_video(
    transcript_text: str,
    word_timestamps: list[dict],
    video_duration: float,
    prompt_version: str = "virality_v1",
) -> dict:
    """Handle videos over 60 minutes by splitting transcript with 5-minute overlap.

    Per DECISION_005: split at 60 minutes with 5-minute overlap window.
    """
    split_point = video_duration / 2
    overlap_seconds = 300.0  # 5 minutes

    # Split words into two halves with overlap
    first_half = [w for w in word_timestamps if w.get("end", 0) <= split_point + overlap_seconds / 2]
    second_half = [w for w in word_timestamps if w.get("start", 0) >= split_point - overlap_seconds / 2]

    first_text = " ".join(w.get("word", "") for w in first_half)
    second_text = " ".join(w.get("word", "") for w in second_half)

    # Run both halves
    result1 = await detect_clips(first_text, first_half, video_duration, prompt_version)
    result2 = await detect_clips(second_text, second_half, video_duration, prompt_version)

    # Merge and dedup
    all_clips = result1.get("clips", []) + result2.get("clips", [])
    all_clips = validate_clips(all_clips, video_duration)
    all_clips = dedup_clips(all_clips)

    return {
        "clips": all_clips,
        "total_candidates": len(all_clips),
        "video_summary": result1.get("video_summary") or result2.get("video_summary", ""),
    }
