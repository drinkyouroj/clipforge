"""Post-processing utilities for clip candidates from Claude API."""

import json
import re


def clean_json_response(raw: str) -> str:
    """Strip markdown fences, trailing commas, and whitespace before parsing."""
    text = raw.strip()
    # Remove markdown code fences
    text = re.sub(r'^```(?:json)?\s*\n?', '', text)
    text = re.sub(r'\n?```\s*$', '', text)
    text = text.strip()
    # Remove trailing commas before } or ]
    text = re.sub(r',\s*([}\]])', r'\1', text)
    return text


def parse_clip_response(raw: str) -> dict:
    """Parse Claude's JSON response with resilience to common formatting issues."""
    cleaned = clean_json_response(raw)
    return json.loads(cleaned)


def validate_clips(clips: list[dict], video_duration: float) -> list[dict]:
    """Validate clip timestamps against video duration. Discard invalid clips."""
    valid = []
    for clip in clips:
        try:
            start = float(clip.get("start_time", -1))
            end = float(clip.get("end_time", -1))

            if start < 0:
                continue
            if end > video_duration + 1.0:  # 1s tolerance per DECISION_005
                continue
            if end <= start:
                continue

            # Recalculate duration (don't trust model output)
            clip["duration"] = round(end - start, 1)
            clip["start_time"] = round(start, 1)
            clip["end_time"] = round(end, 1)

            # Enforce duration constraints
            if clip["duration"] < 15.0 or clip["duration"] > 90.0:
                continue

            # Clamp virality score
            score = clip.get("virality_score")
            if score is not None:
                clip["virality_score"] = max(0, min(100, int(score)))

            valid.append(clip)
        except (ValueError, TypeError):
            continue

    return valid


def dedup_clips(clips: list[dict]) -> list[dict]:
    """Remove clips with >50% time overlap, keeping higher-scored clip."""
    if not clips:
        return clips

    # Sort by virality score descending so we keep the best ones
    sorted_clips = sorted(clips, key=lambda c: c.get("virality_score", 0) or 0, reverse=True)
    kept = []

    for clip in sorted_clips:
        overlap_found = False
        for existing in kept:
            overlap = _overlap_ratio(clip, existing)
            if overlap > 0.5:
                overlap_found = True
                break
        if not overlap_found:
            kept.append(clip)

    return kept


def _overlap_ratio(a: dict, b: dict) -> float:
    """Calculate the overlap ratio between two clips (relative to shorter clip)."""
    overlap_start = max(a["start_time"], b["start_time"])
    overlap_end = min(a["end_time"], b["end_time"])
    overlap_duration = max(0, overlap_end - overlap_start)

    shorter_duration = min(a["duration"], b["duration"])
    if shorter_duration <= 0:
        return 0.0

    return overlap_duration / shorter_duration
