# DECISION 010: CLI/TUI Pipeline Design

## ARCHITECT proposes:

Standalone CLI tool (`clipforge process <video>`) that imports existing backend service functions directly. Linear synchronous pipeline: validate → extract audio → transcribe (local faster-whisper) → detect clips (local LLM via OpenAI-compatible API) → interactive selection → render (FFmpeg + MediaPipe) → local output files.

Key design choices:
- **No database, no S3, no Redis** — all local file I/O
- **Local Whisper** via `faster-whisper` (CTranslate2) — no OpenAI API dependency
- **Local LLM** via OpenAI-compatible endpoint (LocalAI + qwen3.5-9b) — no Anthropic API dependency
- **Synchronous pipeline** — no job queue, no async workers, blocking execution
- **Two new files only** — `cli.py` and `cli_config.py`, everything else reused
- **Rich output** — spinners, progress bars, colored tables, interactive prompts
- **Config resolution** — CLI flags > env vars > config file > interactive prompt

Tradeoffs accepted:
- Synchronous means the user waits for each step. A 3-hour video could take 30+ minutes to transcribe locally.
- No intermediate caching — if the process crashes during rendering, transcription and detection must be re-run.
- `faster-whisper` adds a heavy dependency (~150MB+ model download on first run).

## ADVERSARY attacks:

1. **What happens when faster-whisper runs on a machine with no GPU and a 3-hour video?** The `base` model on CPU will take 30-60 minutes for a 3-hour file. The user sees a spinner saying "Transcribing..." with no progress indication of how far along they are. They don't know if it's 10% done or 90% done. They might kill it thinking it's hung. There's no way to resume — they lose all progress and start over. At minimum this needs a progress bar showing segments completed, and ideally intermediate results saved to disk so a crashed run can resume from the last completed step.

2. **What happens when the local LLM returns garbage JSON?** The spec says "keep existing JSON resilience logic from scorer.py" — but that logic was tuned for Claude Sonnet, which reliably produces JSON with minor formatting issues (markdown fences, trailing commas). A 9B parameter local model will produce substantially worse structured output. It may hallucinate timestamps outside video duration, return partial JSON, mix explanation text with JSON, or simply ignore the JSON instruction entirely. Two retries won't be enough. The prompt was designed for a model 10x larger. This is the highest-risk component — if the LLM can't produce usable clip candidates, the entire tool is worthless.

3. **What happens when FFmpeg crashes mid-render on clip 3 of 5?** The spec says temp files are cleaned up via try/finally. But clips 1 and 2 are already written to the output directory. If the user re-runs the command, does it overwrite them? Skip them? The spec doesn't address idempotency. With multi-platform rendering (`--platform shorts,square`), a crash could leave clip-01-shorts.mp4 but not clip-01-square.mp4 — partial state that's confusing.

4. **What happens when the video has no speech?** A music video, a nature documentary with ambient sound, a gameplay clip with no commentary. faster-whisper returns an empty transcript or near-empty transcript. The LLM receives an empty transcript and either returns no clips (useless) or hallucinates clips (dangerous — fake timestamps). The pipeline should detect this and exit early with a clear message.

5. **The `--platform` flag accepts comma-separated values, but face detection runs per-render.** Face detection + crop computation is the most expensive rendering step (MediaPipe on keyframes every 0.5s). If rendering the same clip for `shorts,square,twitter`, does it run face detection 3 times? It should run once and reuse the face track across all platform renders for the same clip.

6. **Temp directory `/tmp/clipforge-cli/` is world-readable.** Video content could be sensitive. Extracted audio, intermediate files, and transcripts sitting in a predictable `/tmp/` path with default permissions is a data leak vector on shared machines.

## JUDGE decides:

**Proceed with modifications.** The core design is sound. Required changes:

1. **Transcription progress:** Replace spinner with progress bar based on audio segments processed. Do NOT add crash-resume — YAGNI for v1. Users can choose `--whisper-model tiny` for speed.

2. **LLM resilience:** Increase retries from 2 to 3. Use temperature 0.1 to reduce randomness. If 3 retries produce zero valid clips, print warning suggesting a more capable model. Existing timestamp/score validation in scorer.py handles hallucinated values.

3. **Partial render idempotency:** Skip existing output files by default. Print "Skipping clip N (already exists)". Add `--overwrite` flag to force re-render.

4. **Empty transcript guard:** After transcription, if fewer than 50 words, print warning and exit: "Transcript too short (N words). ClipForge works best with speech-heavy content."

5. **Face detection reuse:** Run face detection once per clip, cache in memory, reuse across platform renders. `render_clip_local()` accepts optional `face_track` parameter.

6. **Temp directory security:** Use `tempfile.mkdtemp(prefix="clipforge-")` instead of fixed path.

**Not required (overreach):** Crash-resume for transcription, `--json` output.

## Implementation notes:

- Add `--overwrite` flag to spec
- Update temp file handling in spec
- All six judge requirements must be reflected in the implementation plan

---

## ADVERSARY attacks implementation plan (round 2):

1. **Chunked transcription timestamp bug:** split_audio creates chunks but transcribe_local returns timestamps relative to each chunk (starting at 0.0). Without offset correction, clip detection produces wrong timestamps. **JUDGE: Fix required — add time_offset = chunk_idx * chunk_duration.**

2. **FFmpeg render timeout too aggressive:** 600s timeout kills renders of long clips from high-res sources on CPU. **JUDGE: Remove timeout entirely. User can Ctrl+C.**

3. **LLM errors silenced:** detect_clips_local catches all exceptions and returns empty clips. User sees "try a more capable model" when the real problem is connection refused. **JUDGE: Surface actual error message in return dict.**

All three fixes applied to implementation plan.
