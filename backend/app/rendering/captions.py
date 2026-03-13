"""ASS subtitle generation with per-word highlighting."""


def group_words_into_lines(
    words: list[dict], max_words: int = 4, pause_threshold: float = 0.5
) -> list[list[dict]]:
    """Group word timestamps into display lines.

    Splits at max_words or when gap between words exceeds pause_threshold.
    """
    if not words:
        return []

    lines: list[list[dict]] = []
    current_line: list[dict] = []

    for i, word in enumerate(words):
        # Check for long pause (split point)
        if current_line and i > 0:
            gap = word["start"] - words[i - 1]["end"]
            if gap > pause_threshold or len(current_line) >= max_words:
                lines.append(current_line)
                current_line = []

        current_line.append(word)

    if current_line:
        lines.append(current_line)

    return lines


def _format_ass_time(seconds: float) -> str:
    """Format seconds as ASS timestamp: H:MM:SS.cc (centiseconds)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _escape_ass_text(text: str) -> str:
    """Escape characters that have special meaning in ASS format."""
    # ASS uses backslash for formatting codes — escape literal backslashes
    text = text.replace("\\", "\\\\")
    # Newlines in ASS are \\N
    text = text.replace("\n", "\\N")
    # Braces are used for override tags
    text = text.replace("{", "\\{").replace("}", "\\}")
    return text


def generate_ass_captions(
    word_timestamps: list[dict],
    clip_start_time: float,
    max_words_per_line: int = 4,
    play_res_x: int = 1080,
    play_res_y: int = 1920,
) -> str:
    """Generate ASS subtitle content with per-word highlighting.

    Args:
        word_timestamps: List of {"word": str, "start": float, "end": float}
        clip_start_time: Start time of clip in original video (for rebasing to 0)
        max_words_per_line: Max words per display line
        play_res_x: ASS PlayResX (should match output width)
        play_res_y: ASS PlayResY (should match output height)

    Returns:
        Complete ASS subtitle file content as string
    """
    header = f"""[Script Info]
Title: ClipForge Captions
ScriptType: v4.00+
PlayResX: {play_res_x}
PlayResY: {play_res_y}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,18,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,2,0,2,20,20,60,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    # Filter words within clip bounds and rebase timestamps to 0
    clip_words = []
    for w in word_timestamps:
        if w["start"] >= clip_start_time:
            clip_words.append({
                "word": w["word"],
                "start": w["start"] - clip_start_time,
                "end": w["end"] - clip_start_time,
            })

    lines = group_words_into_lines(clip_words, max_words=max_words_per_line)

    dialogue_lines = []
    for line_words in lines:
        if not line_words:
            continue

        # Build text with per-word highlighting.
        # For each moment in time, one word is "active" (yellow), rest are white.
        # We create one dialogue event per word-highlight phase.
        for active_idx, active_word in enumerate(line_words):
            word_start = _format_ass_time(active_word["start"])
            word_end = _format_ass_time(active_word["end"])

            parts = []
            for j, w in enumerate(line_words):
                escaped = _escape_ass_text(w["word"])
                if j == active_idx:
                    parts.append("{\\c&H0000FFFF&}" + escaped)
                else:
                    parts.append("{\\c&H00FFFFFF&}" + escaped)

            text = " ".join(parts)
            dialogue_lines.append(
                f"Dialogue: 0,{word_start},{word_end},Default,,0,0,0,,{text}"
            )

    return header + "\n".join(dialogue_lines) + "\n"
