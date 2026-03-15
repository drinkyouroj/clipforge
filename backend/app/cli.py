"""ClipForge CLI — standalone video clip detection and rendering."""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import Progress
from rich.table import Table

from faster_whisper import WhisperModel
from openai import OpenAI

from app.cli_config import resolve_config, interactive_setup, DEFAULT_CONFIG_PATH
from app.videos.validation import validate_magic_bytes, validate_with_ffprobe
from app.clip_detection.detector import (
    _load_prompt,
    format_transcript_with_timestamps,
    _format_duration,
)
from app.clip_detection.scorer import parse_clip_response, validate_clips, dedup_clips
from app.rendering.reframe import build_face_track, compute_crop_params
from app.rendering.captions import generate_ass_captions
from app.rendering.ffmpeg_cmd import build_ffmpeg_command
from app.rendering.specs import get_platform_spec

app = typer.Typer(name="clipforge", help="AI-powered viral clip detection and rendering.")
console = Console()

VERSION = "1.0.0"
MAX_LLM_RETRIES = 3


def transcribe_local(audio_path: str, model_name: str = "base") -> dict:
    """Transcribe audio using local faster-whisper model.

    Returns {"text": str, "words": [{"word": str, "start": float, "end": float}]}
    """
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, info = model.transcribe(audio_path, word_timestamps=True)

    all_text = []
    all_words = []

    for segment in segments:
        all_text.append(segment.text.strip())
        if segment.words:
            for w in segment.words:
                all_words.append({
                    "word": w.word.strip(),
                    "start": w.start,
                    "end": w.end,
                })

    return {
        "text": " ".join(all_text),
        "words": all_words,
        "language": info.language if hasattr(info, "language") else "en",
    }


def detect_clips_local(
    transcript_text: str,
    word_timestamps: list[dict],
    video_duration: float,
    llm_url: str,
    llm_model: str,
    prompt_version: str = "virality_v1",
) -> dict:
    """Detect viral clips using a local OpenAI-compatible LLM.

    Returns {"clips": [...], "total_candidates": int, "video_summary": str}
    """
    formatted_transcript = format_transcript_with_timestamps(word_timestamps)
    prompt_template = _load_prompt(prompt_version)
    prompt = prompt_template.replace("{transcript_text}", formatted_transcript)
    prompt = prompt.replace("{video_duration:.1f}", f"{video_duration:.1f}")
    prompt = prompt.replace("{video_duration_formatted}", _format_duration(video_duration))

    client = OpenAI(base_url=llm_url, api_key="not-needed")

    for attempt in range(MAX_LLM_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=llm_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4096,
                temperature=0.1,
                timeout=120,
            )

            raw_text = response.choices[0].message.content
            result = parse_clip_response(raw_text)
            clips = result.get("clips", [])
            clips = validate_clips(clips, video_duration)
            clips = dedup_clips(clips)

            if clips or attempt == MAX_LLM_RETRIES:
                return {
                    "clips": clips,
                    "total_candidates": len(clips),
                    "video_summary": result.get("video_summary", ""),
                }
            # No valid clips — retry
            continue

        except Exception as e:
            if attempt == MAX_LLM_RETRIES:
                return {
                    "clips": [], "total_candidates": 0,
                    "video_summary": "",
                    "error": f"{type(e).__name__}: {e}",
                }
            continue


def render_clip_local(
    video_path: str,
    start_time: float,
    end_time: float,
    platform: str,
    output_path: str,
    word_timestamps: list[dict],
    no_captions: bool,
    face_track: dict | None,
    tmp_dir: str,
    video_width: int,
    video_height: int,
) -> dict:
    """Render a single clip to a local file.

    Returns {"face_track": dict} so it can be reused for multi-platform renders.
    """
    duration = end_time - start_time
    spec = get_platform_spec(platform)

    # Face detection (or reuse cached track)
    if face_track is None:
        face_track = build_face_track(video_path, start_time, duration)

    # Compute crop
    crop = compute_crop_params(face_track, video_width, video_height, spec["aspect_ratio"])

    # Generate captions
    ass_path = None
    if not no_captions and word_timestamps:
        os.makedirs(tmp_dir, exist_ok=True)
        clip_words = [
            w for w in word_timestamps
            if w["start"] >= start_time and w["end"] <= end_time
        ]
        if clip_words:
            ass_content = generate_ass_captions(
                clip_words, start_time,
                play_res_x=spec["width"], play_res_y=spec["height"],
            )
            ass_path = os.path.join(tmp_dir, f"captions_{start_time:.0f}.ass")
            with open(ass_path, "w") as f:
                f.write(ass_content)

    # Build and run FFmpeg command
    cmd = build_ffmpeg_command(
        input_path=video_path,
        output_path=output_path,
        start_time=start_time,
        duration=duration,
        crop=crop,
        width=spec["width"],
        height=spec["height"],
        fps=spec.get("fps", 30),
        aspect_ratio=spec["aspect_ratio"],
        ass_path=ass_path,
    )

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    subprocess.run(cmd, check=True, capture_output=True)

    return {"face_track": face_track}


def version_callback(value: bool):
    if value:
        console.print(f"clipforge {VERSION}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(False, "--version", callback=version_callback, is_eager=True),
):
    pass


@app.command()
def setup(
    config: str = typer.Option(DEFAULT_CONFIG_PATH, "--config", help="Config file path"),
):
    """Interactive configuration for LLM endpoint and Whisper model."""
    interactive_setup(config)


@app.command()
def process(
    video_path: str = typer.Argument(..., help="Path to video file"),
    platform: str = typer.Option("shorts", help="Target platform(s), comma-separated"),
    min_score: int = typer.Option(None, "--min-score", help="Auto-render clips above this score"),
    all_clips: bool = typer.Option(False, "--all", help="Render all clips"),
    detect_only: bool = typer.Option(False, "--detect-only", help="Detect clips without rendering"),
    output_dir: str = typer.Option(None, "-o", "--output-dir", help="Output directory"),
    max_clips: int = typer.Option(15, "--max-clips", help="Max clip candidates"),
    no_captions: bool = typer.Option(False, "--no-captions", help="Skip caption burn-in"),
    whisper_model: str = typer.Option(None, "--whisper-model", help="Whisper model name"),
    llm_url: str = typer.Option(None, "--llm-url", help="LLM endpoint URL"),
    llm_model: str = typer.Option(None, "--llm-model", help="LLM model name"),
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite existing output files"),
    config: str = typer.Option(DEFAULT_CONFIG_PATH, "--config", help="Config file path"),
):
    """Process a video file: detect viral clips and render them."""
    # Resolve config
    cfg = resolve_config(
        cli_llm_url=llm_url,
        cli_llm_model=llm_model,
        cli_whisper_model=whisper_model,
        config_path=config,
    )

    # Check required config
    if not cfg["llm_url"] or not cfg["llm_model"]:
        console.print("[yellow]LLM not configured. Running setup...[/yellow]")
        cfg = interactive_setup(config)

    # Parse platforms
    platforms = [p.strip() for p in platform.split(",")]
    valid_platforms = {"shorts", "tiktok", "reels", "square", "twitter"}
    for p in platforms:
        if p not in valid_platforms:
            console.print(f"[red]Unknown platform: {p}[/red]")
            raise typer.Exit(code=1)

    # Set output directory
    if output_dir is None:
        stem = Path(video_path).stem
        output_dir = os.path.join(".", "clipforge-output", stem)

    # Create temp directory (secure, per DECISION_010)
    tmp_dir = tempfile.mkdtemp(prefix="clipforge-")

    try:
        # === Step 1: Validate ===
        with console.status("[bold blue]Validating video..."):
            if not os.path.isfile(video_path):
                console.print(f"[red]File not found: {video_path}[/red]")
                raise typer.Exit(code=1)

            if not validate_magic_bytes(video_path):
                console.print("[red]File is not a supported video format.[/red]")
                raise typer.Exit(code=1)

            probe = validate_with_ffprobe(video_path)
            if probe is None:
                console.print("[red]Invalid video or missing audio track.[/red]")
                raise typer.Exit(code=1)

        duration = probe["duration"]
        console.print(f"[green]Valid video:[/green] {Path(video_path).name} ({duration:.0f}s)")

        # === Step 2: Extract audio ===
        audio_path = os.path.join(tmp_dir, "audio.mp3")
        with console.status("[bold blue]Extracting audio..."):
            from app.transcription.audio import extract_audio
            extract_audio(video_path, audio_path)
        console.print("[green]Audio extracted.[/green]")

        # === Step 3: Transcribe ===
        from app.transcription.audio import split_audio
        chunks = split_audio(audio_path, tmp_dir)
        if len(chunks) <= 1:
            chunks = [audio_path]

        chunk_duration = 3000

        all_words = []
        all_text = []
        with Progress() as progress:
            task = progress.add_task(
                f"[blue]Transcribing with {cfg['whisper_model']} model...",
                total=len(chunks),
            )
            for chunk_idx, chunk_path in enumerate(chunks):
                result = transcribe_local(chunk_path, cfg["whisper_model"])
                # Apply timestamp offset for chunked audio (DECISION_010-B fix)
                time_offset = chunk_idx * chunk_duration if len(chunks) > 1 else 0.0
                for w in result["words"]:
                    w["start"] += time_offset
                    w["end"] += time_offset
                all_words.extend(result["words"])
                all_text.append(result["text"])
                progress.advance(task)

        transcript = {
            "text": " ".join(all_text),
            "words": all_words,
        }

        word_count = len(transcript["words"])
        console.print(f"[green]Transcribed:[/green] {word_count} words")

        # Empty transcript guard (DECISION_010)
        if word_count < 50:
            console.print(
                f"[red]Transcript too short ({word_count} words). "
                "ClipForge works best with speech-heavy content.[/red]"
            )
            raise typer.Exit(code=1)

        # === Step 4: Detect clips ===
        with console.status("[bold blue]Detecting viral clips..."):
            try:
                if duration > 3600:
                    # Long video: split and detect in halves
                    split_point = duration / 2
                    overlap = 300.0
                    first_words = [w for w in transcript["words"] if w.get("end", 0) <= split_point + overlap / 2]
                    second_words = [w for w in transcript["words"] if w.get("start", 0) >= split_point - overlap / 2]

                    result1 = detect_clips_local(
                        " ".join(w["word"] for w in first_words), first_words,
                        duration, cfg["llm_url"], cfg["llm_model"],
                    )
                    result2 = detect_clips_local(
                        " ".join(w["word"] for w in second_words), second_words,
                        duration, cfg["llm_url"], cfg["llm_model"],
                    )
                    all_det_clips = result1["clips"] + result2["clips"]
                    all_det_clips = validate_clips(all_det_clips, duration)
                    all_det_clips = dedup_clips(all_det_clips)
                    detection_result = {
                        "clips": all_det_clips,
                        "total_candidates": len(all_det_clips),
                        "video_summary": result1.get("video_summary") or result2.get("video_summary", ""),
                    }
                else:
                    detection_result = detect_clips_local(
                        transcript["text"], transcript["words"],
                        duration, cfg["llm_url"], cfg["llm_model"],
                    )
            except Exception as e:
                if "Connection" in str(type(e).__name__) or "connection" in str(e).lower():
                    console.print(
                        f"[red]Cannot reach LLM at {cfg['llm_url']} — is the server running?[/red]"
                    )
                else:
                    console.print(f"[red]Clip detection failed: {e}[/red]")
                raise typer.Exit(code=1)

        clips = detection_result["clips"][:max_clips]

        if not clips:
            error_detail = detection_result.get("error", "")
            if error_detail:
                console.print(f"[red]Clip detection failed: {error_detail}[/red]")
            else:
                console.print(
                    "[yellow]No clips detected. Try a more capable LLM model "
                    "or a video with more engaging content.[/yellow]"
                )
            raise typer.Exit(code=0)

        # Display clip candidates table
        table = Table(title=f"Clip Candidates ({len(clips)} found)")
        table.add_column("#", style="bold", width=3)
        table.add_column("Score", width=5)
        table.add_column("Hook", max_width=40)
        table.add_column("Type", width=12)
        table.add_column("Start", width=8)
        table.add_column("End", width=8)
        table.add_column("Duration", width=8)

        clips.sort(key=lambda c: c.get("virality_score", 0), reverse=True)

        for i, clip in enumerate(clips, 1):
            score = clip.get("virality_score", 0)
            if score >= 80:
                score_style = "green"
            elif score >= 60:
                score_style = "yellow"
            else:
                score_style = "red"

            start = clip.get("start_time", 0)
            end = clip.get("end_time", 0)
            table.add_row(
                str(i),
                f"[{score_style}]{score}[/{score_style}]",
                clip.get("hook", "")[:40],
                clip.get("clip_type", ""),
                f"{start:.1f}s",
                f"{end:.1f}s",
                f"{end - start:.0f}s",
            )

        console.print(table)

        if detection_result.get("video_summary"):
            console.print(f"\n[dim]{detection_result['video_summary']}[/dim]\n")

        # === Step 5: Select clips ===
        if detect_only:
            console.print("[green]Detection complete (--detect-only).[/green]")
            raise typer.Exit(code=0)

        if all_clips:
            selected_indices = list(range(len(clips)))
        elif min_score is not None:
            selected_indices = [
                i for i, c in enumerate(clips)
                if c.get("virality_score", 0) >= min_score
            ]
            if not selected_indices:
                console.print(f"[yellow]No clips scored >= {min_score}.[/yellow]")
                raise typer.Exit(code=0)
            console.print(f"[green]Auto-selected {len(selected_indices)} clips with score >= {min_score}[/green]")
        else:
            # Interactive selection
            selection = console.input(
                "\n[bold]Select clips to render (e.g. 1,3,5 or all):[/bold] "
            ).strip()

            if selection.lower() == "all":
                selected_indices = list(range(len(clips)))
            else:
                try:
                    selected_indices = [int(s.strip()) - 1 for s in selection.split(",")]
                    for idx in selected_indices:
                        if idx < 0 or idx >= len(clips):
                            console.print(f"[red]Invalid clip number: {idx + 1}[/red]")
                            raise typer.Exit(code=1)
                except ValueError:
                    console.print("[red]Invalid selection. Use numbers separated by commas.[/red]")
                    raise typer.Exit(code=1)

        selected_clips = [clips[i] for i in selected_indices]
        console.print(f"\n[green]{len(selected_clips)} clip(s) selected for rendering.[/green]")

        # === Step 6: Render ===
        os.makedirs(output_dir, exist_ok=True)

        # Get video dimensions from ffprobe streams
        video_width = 1920
        video_height = 1080
        for stream in probe.get("streams", []):
            if stream.get("codec_type") == "video":
                video_width = int(stream.get("width", 1920))
                video_height = int(stream.get("height", 1080))
                break

        rendered_files = []
        total_renders = len(selected_clips) * len(platforms)

        with Progress() as progress:
            render_task = progress.add_task("[blue]Rendering clips...", total=total_renders)
            render_num = 0

            for i, clip in enumerate(selected_clips):
                clip_num = selected_indices[i] + 1
                score = clip.get("virality_score", 0)
                start = clip.get("start_time", 0)
                end = clip.get("end_time", 0)

                face_track_cache = None  # Reuse across platforms for same clip

                for plat in platforms:
                    render_num += 1
                    filename = f"clip-{clip_num:02d}-score{score}-{plat}.mp4"
                    out_path = os.path.join(output_dir, filename)

                    # Idempotency: skip existing files (DECISION_010)
                    if os.path.exists(out_path) and not overwrite:
                        console.print(f"  [dim]Skipping clip {clip_num} {plat} (already exists)[/dim]")
                        rendered_files.append({
                            "clip": clip_num, "platform": plat,
                            "duration": f"{end - start:.0f}s",
                            "path": out_path, "size": os.path.getsize(out_path),
                            "skipped": True,
                        })
                        progress.advance(render_task)
                        continue

                    progress.update(
                        render_task,
                        description=f"[blue]Rendering clip {clip_num} [{plat}] ({render_num}/{total_renders})...",
                    )

                    try:
                        result = render_clip_local(
                            video_path=video_path,
                            start_time=start,
                            end_time=end,
                            platform=plat,
                            output_path=out_path,
                            word_timestamps=transcript["words"],
                            no_captions=no_captions,
                            face_track=face_track_cache,
                            tmp_dir=tmp_dir,
                            video_width=video_width,
                            video_height=video_height,
                        )
                        face_track_cache = result["face_track"]

                        file_size = os.path.getsize(out_path) if os.path.exists(out_path) else 0
                        rendered_files.append({
                            "clip": clip_num, "platform": plat,
                            "duration": f"{end - start:.0f}s",
                            "path": out_path, "size": file_size,
                            "skipped": False,
                        })
                    except Exception as e:
                        console.print(f"  [red]Failed to render clip {clip_num} [{plat}]: {e}[/red]")

                    progress.advance(render_task)

        # === Step 7: Summary ===
        if rendered_files:
            summary = Table(title="Rendered Clips")
            summary.add_column("Clip", width=5)
            summary.add_column("Platform", width=10)
            summary.add_column("Duration", width=8)
            summary.add_column("Size", width=10)
            summary.add_column("Path")

            for rf in rendered_files:
                size_mb = rf["size"] / (1024 * 1024) if rf["size"] else 0
                status = " [dim](cached)[/dim]" if rf.get("skipped") else ""
                summary.add_row(
                    str(rf["clip"]),
                    rf["platform"],
                    rf["duration"],
                    f"{size_mb:.1f} MB",
                    rf["path"] + status,
                )

            console.print(summary)
            console.print(f"\n[green bold]Done! {len(rendered_files)} clip(s) in {output_dir}[/green bold]")
        else:
            console.print("[yellow]No clips were rendered.[/yellow]")

    finally:
        # Clean up temp directory
        shutil.rmtree(tmp_dir, ignore_errors=True)
