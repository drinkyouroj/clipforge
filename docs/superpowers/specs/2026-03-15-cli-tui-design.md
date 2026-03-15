# ClipForge CLI/TUI Design Spec

## Goal

A standalone command-line tool that processes a local video file — validates, transcribes (local Whisper), detects viral clips (local LLM), and renders selected clips — with Rich terminal output. No server, database, or cloud APIs required.

## Architecture

Two new files in the backend: `cli.py` (entry point, pipeline orchestration, Rich display) and `cli_config.py` (config file resolution). The CLI imports existing service-layer functions directly — no new abstractions over validation, transcription, clip detection, or rendering.

All processing is local. Transcription uses `faster-whisper` (local model). Clip detection uses an OpenAI-compatible LLM endpoint (e.g., LocalAI with qwen3.5-9b). Rendering uses FFmpeg + MediaPipe locally. Output is written to local disk.

The `openai` Python SDK (sync client) is used to call the local LLM endpoint via its `base_url` parameter. This is the standard approach for OpenAI-compatible APIs.

## CLI Interface

### Commands

```
clipforge process <video-path> [options]    # Main pipeline
clipforge setup                             # Interactive config (LLM endpoint, whisper model)
clipforge --version
```

### Entry Point Registration

Add to `pyproject.toml` (or `setup.cfg`):

```toml
[project.scripts]
clipforge = "app.cli:app"
```

For development, install with `pip install -e .` to register the `clipforge` command.

### Flags for `process`

| Flag | Default | Description |
|------|---------|-------------|
| `--platform` | `shorts` | Target platform: shorts, tiktok, reels, square, twitter. Comma-separated for multiple (e.g. `shorts,square`) |
| `--min-score N` | (none) | Auto-render clips scoring >= N, skip interactive selection |
| `--all` | false | Render all detected clips, skip interactive selection |
| `--detect-only` | false | Run steps 1-5 only (validate, transcribe, detect, display). No rendering |
| `--output-dir / -o` | `./clipforge-output/<video-stem>/` | Output directory |
| `--max-clips N` | 15 | Cap on clip candidates to detect |
| `--no-captions` | false | Skip caption burn-in |
| `--whisper-model` | `base` | Whisper model: tiny, base, small, medium, large-v3 |
| `--llm-url` | (from config) | OpenAI-compatible LLM endpoint URL |
| `--llm-model` | (from config) | LLM model name |
| `--overwrite` | false | Re-render clips even if output file already exists |
| `--config` | `~/.config/clipforge/config.toml` | Path to config file |

## Config File

Location: `~/.config/clipforge/config.toml`

```toml
[llm]
base_url = "http://kona.unroots.net:8080"
model = "qwen3.5-9b"

[whisper]
model = "base"
```

### Resolution Order (first wins)

1. CLI flags (`--llm-url`, `--llm-model`, `--whisper-model`)
2. Environment variables (`CLIPFORGE_LLM_URL`, `CLIPFORGE_LLM_MODEL`, `CLIPFORGE_WHISPER_MODEL`)
3. Config file
4. Interactive prompt on first run (saves to config file)

`clipforge setup` forces the interactive prompt, overwriting existing config.

## Pipeline Flow

The `process` command executes a linear pipeline:

```
1. Validate        → ffprobe: confirm video+audio streams, extract duration
2. Extract audio   → FFmpeg: mono MP3, chunk if >24MB
3. Transcribe      → faster-whisper: local model, word-level timestamps
4. Detect clips    → Local LLM: existing virality prompt, JSON response parsing
5. Select clips    → Interactive Rich prompt (or auto via --min-score/--all)
6. Render clips    → Per-clip per-platform: face detect → crop → captions → FFmpeg → local file
7. Summary         → Rich table of output files with paths and sizes
```

If `--detect-only` is set, the pipeline stops after step 5 (no rendering).

If `--platform` contains multiple values (e.g., `shorts,square`), step 6 renders each selected clip once per platform.

### Rich Output Per Stage

- **Steps 1-2:** Spinner with status text (e.g., "Validating video...", "Extracting audio...")
- **Step 3:** Progress bar based on audio segments processed (e.g., "Transcribing [3/8 segments]...")
- **Step 4:** Spinner during detection, then Rich table:
  - Columns: `#`, `Score`, `Hook`, `Type`, `Start`, `End`, `Duration`
  - Sorted by score descending
  - Color gradient on score (green >=80, yellow >=60, red <60)
- **Step 5:** Prompt: `Select clips to render (e.g. 1,3,5 or all):`
- **Step 6:** Progress bar per clip ("Rendering clip 2/4 [shorts]...")
- **Step 7:** Summary table: `Clip`, `Platform`, `Duration`, `Size`, `Path`

### Error Handling

- If any step fails, print the error in red (`rich.console.print`) and exit with code 1
- **Empty transcript guard:** If transcription yields fewer than 50 words, exit with: "Transcript too short (N words). ClipForge works best with speech-heavy content."
- **LLM connection errors:** Detect connection failures early and print: "Cannot reach LLM at {url} -- is the server running?" with exit code 1
- **LLM resilience:** 3 retries with temperature 0.1. If all retries produce zero valid clips, print warning suggesting a more capable model
- **LLM timeout:** 120-second timeout per request
- **Render idempotency:** Skip clips whose output file already exists (print "Skipping clip N (already exists)"). Override with `--overwrite`
- Temp files cleaned up via try/finally regardless of success/failure
- Temp directory: `tempfile.mkdtemp(prefix="clipforge-")` (secure, unpredictable path)

### Rendering Optimization

- Face detection runs once per clip, cached in memory
- When rendering the same clip for multiple platforms, the face track is reused
- `render_clip_local()` accepts an optional `face_track` parameter

## File Structure

### New Files

- `backend/app/cli.py` — Typer app, pipeline function, Rich display logic
- `backend/app/cli_config.py` — Config file read/write, resolution logic, `setup` command helper
- `backend/pyproject.toml` — Entry point registration for `clipforge` command

### Reused Existing Modules (no modifications needed)

| Module | Functions Used |
|--------|---------------|
| `videos/validation.py` | `validate_magic_bytes()`, `validate_with_ffprobe()` |
| `transcription/audio.py` | `extract_audio()`, `split_audio()` |
| `clip_detection/detector.py` | `format_transcript_with_timestamps()`, `_load_prompt()`, `_format_time()`, `_format_duration()` |
| `clip_detection/scorer.py` | `parse_clip_response()`, `validate_clips()`, `dedup_clips()` |
| `clip_detection/prompts/virality_v1.txt` | Prompt template (loaded from file) |
| `rendering/reframe.py` | `detect_faces_in_frames()`, `smooth_face_track()`, `compute_crop_params()` |
| `rendering/captions.py` | `generate_ass_captions()` |
| `rendering/ffmpeg_cmd.py` | `build_ffmpeg_command()` |
| `rendering/specs.py` | Platform specs dict |

### New Functions Needed (in cli.py)

These replace the Anthropic/OpenAI API/S3/DB-coupled functions from the web backend:

| Function | What it does |
|----------|-------------|
| `transcribe_local()` | Uses `faster-whisper` to transcribe audio. Returns `{"text": str, "words": [{"word": str, "start": float, "end": float}]}`. Maps from faster-whisper's `Word` objects (`.start`, `.end`, `.word` attributes) to this dict format. |
| `detect_clips_local()` | Loads virality prompt, formats transcript using existing helpers, calls local LLM via `openai.OpenAI(base_url=...)`. Passes response through existing `parse_clip_response()`, `validate_clips()`, `dedup_clips()`. |
| `render_clip_local()` | Takes local video path, clip boundaries, platform spec, output path. Runs face detection, builds FFmpeg command using existing helpers, executes FFmpeg subprocess, writes output file. No S3 or DB. |

## Dependencies

### New packages to add to requirements.txt

- `typer>=0.9.0` — CLI framework
- `faster-whisper>=1.0.0` — Local Whisper transcription
- `tomli>=2.0.0` — TOML config file reading (Python <3.11 compat)
- `tomli-w>=1.0.0` — TOML config file writing

### Already available

- `rich` — Already installed (transitive dependency of typer)
- `openai` — Already installed (used with custom `base_url` for OpenAI-compatible local LLM endpoint)

## Output Structure

```
./clipforge-output/
  my-podcast-episode/
    clip-01-score87-shorts.mp4
    clip-02-score72-shorts.mp4
    clip-03-score65-square.mp4
```

Filename format: `clip-{NN}-score{score}-{platform}.mp4`

## What This Does NOT Include

- Database storage (no DB needed)
- S3/cloud storage (all local)
- User auth or billing
- ARQ job queue (synchronous pipeline)
- Web UI or API server
- YouTube/URL ingest (local files only)
- Multi-language transcription (English only, matching existing scope)
- `--json` output mode (can be added later if scripting use cases emerge)
