# Render Pipeline Design Spec

## Goal

Build the Week 3 render pipeline for ClipForge: a three-step chained job system that takes a selected clip + target platform, applies smart face-based reframing, burns in word-highlighted captions, and produces a platform-spec'd MP4 ready for download.

## Architecture

Three-step ARQ task chain triggered by `POST /exports`:

```
POST /exports → Create Export + Job(type=render) →
  Step 1: prepare_render   — download video, face detect, generate ASS captions
  Step 2: execute_render   — assemble + run FFmpeg command
  Step 3: upload_output    — upload to S3, update DB, generate download URL, cleanup
```

Steps share state via:
- A temp directory: `/tmp/clipforge/render/{job_id}/`
- A JSONB `render_context` field on the Job record (file paths, face track reference, platform specs)

Each step is an independent ARQ task. On success, the step enqueues the next step. On failure, it sets `Job.status = 'failed'` and `Export.status = 'failed'`, records the error, and cleans up temp files.

## Decisions Made

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Pipeline structure | Multi-step chain (3 tasks) | Granular retry — face detection failure doesn't re-download; FFmpeg crash doesn't re-analyze |
| Face detection storage | JSONB on Clip (`face_track` column) | Reusable across multiple exports of same clip; skip re-detection on re-export |
| Caption format | ASS/SSA with per-word highlight | Native FFmpeg support via `ass` filter; true word-level highlighting (yellow active word, white rest) |
| Export model | Export-centric — one Export per clip-platform | Each platform has different specs (resolution, max duration); clean rate limiting by counting Exports |

## New Backend Modules

### `backend/app/rendering/`

#### `specs.py` — Platform specifications

Lookup table for all five platforms from CLAUDE.md:

| Platform | Key | Aspect | Resolution | FPS | Max Duration |
|----------|-----|--------|------------|-----|-------------|
| YouTube Shorts | `shorts` | 9:16 | 1080x1920 | 30 | 60s |
| TikTok | `tiktok` | 9:16 | 1080x1920 | 30 | 60s |
| Instagram Reels | `reels` | 9:16 | 1080x1920 | 30 | 90s |
| Instagram Square | `square` | 1:1 | 1080x1080 | 30 | 60s |
| X (Twitter) | `twitter` | 16:9 | 1280x720 | 30 | 140s |

All exports: MP4 H.264, AAC 192kbps stereo, loudness normalized to -14 LUFS.

Returns a dataclass/dict with all fields needed for FFmpeg command assembly.

#### `reframe.py` — Face detection + smart crop

Uses `mediapipe` (MIT license) for face detection:

1. Extract keyframes from clip segment (every 0.5s) using FFmpeg
2. Run mediapipe face detection on each keyframe
3. Build face position track: `[{"t": 0.0, "x": 540, "y": 360}, ...]`
4. Smooth track with moving average (window=15 frames) to prevent jitter
5. Store as JSONB in `Clip.face_track`

Crop calculation per aspect ratio:
- **9:16**: `crop=ih*(9/16):ih:smooth_x:0` — full height, width = height * 9/16
- **1:1**: `crop=ih:ih:smooth_x:0` — full height, square
- **16:9**: No crop needed (original ratio) — just scale to target resolution

Fallback: If no face detected in any keyframe, use center crop.

Skip face detection if `Clip.face_track` is already populated (reuse from prior export).

#### `captions.py` — ASS subtitle generation

Input: `Transcript.word_timestamps` (JSONB array of `{"word": "hello", "start": 0.0, "end": 0.5}`)

Process:
1. Group words into display lines (~3-4 words per line, or split at natural pauses >0.5s)
2. For each line, generate ASS dialogue events where:
   - Each word gets its own timed override tag
   - Active word: yellow (`{\c&H0000FFFF&}`)
   - Inactive words: white (`{\c&H00FFFFFF&}`)
3. Style: Arial font, size 18, black outline (border=2), bottom-center alignment
4. Write `.ass` file to temp directory

The ASS header defines the default style. Each dialogue line uses `{\kf}` karaoke fill tags or explicit color overrides per word timing.

#### `ffmpeg_cmd.py` — Command assembly

Builds the FFmpeg command from:
- Input video path (local temp file)
- Crop parameters (from face track + target aspect ratio)
- Scale to target resolution
- ASS subtitle path
- Audio: AAC 192kbps stereo, loudnorm filter (-14 LUFS)
- Video: H.264, preset fast, CRF 23
- `-movflags +faststart` for web streaming
- `-t {duration}` to trim to clip boundaries
- `-ss {start_time}` to seek to clip start

Template (9:16 example):
```bash
ffmpeg -ss {start_time} -i {input_path} -t {duration} \
  -vf "crop={crop_w}:{crop_h}:{crop_x}:{crop_y},scale={width}:{height},ass={ass_path}" \
  -c:v libx264 -preset fast -crf 23 \
  -c:a aac -b:a 192k -ac 2 \
  -af loudnorm=I=-14:LRA=11:TP=-1.5 \
  -movflags +faststart \
  -y {output_path}
```

For 16:9 (no crop needed): omit `crop`, just `scale=1280:720`.

Returns the command as a list of args for `subprocess.run()` or `asyncio.create_subprocess_exec()`.

#### `pipeline.py` — Task orchestration

Three ARQ task functions:

**`prepare_render_task(ctx, export_id)`:**
1. Load Export (via `export_id`) + associated Job (via `Export.job_id`) + Clip + Video + Transcript
2. Set `Job.status = 'running'`, `Job.started_at = now()`, `Export.status = 'rendering'`
3. Create temp dir `/tmp/clipforge/render/{job_id}/`
4. Download video from S3 to `/tmp/clipforge/render/{job_id}/input.mp4`
5. Run face detection if `Clip.face_track` is None → store result on Clip
6. Generate ASS subtitle file → `/tmp/clipforge/render/{job_id}/captions.ass`
   - **Important:** Caption timestamps must be relative to 0 (not original video time), since FFmpeg `-ss` before `-i` resets the timeline
7. Store paths in `Job.render_context` JSONB
8. Enqueue `execute_render_task`

**`execute_render_task(ctx, export_id)`:**
1. Load Export + Job (via `Export.job_id`), read `render_context` for paths
2. Look up platform specs
3. Build FFmpeg command from specs + face track + crop + ASS path
4. Run FFmpeg via `asyncio.create_subprocess_exec()`
5. Verify output file exists and size > 0
6. Sanity check: output file size < 2x input segment size (catch FFmpeg misconfiguration)
7. Update `render_context` with output path
8. Enqueue `upload_output_task`

**`upload_output_task(ctx, export_id)`:**
1. Load Export + Job (via `Export.job_id`), read `render_context`
2. Upload rendered file to S3: `renders/{user_id}/{export_id}.mp4`
3. Generate presigned download URL (1 hour expiry)
4. Update Export: `s3_key`, `download_url`, `expires_at`, `status = 'rendered'`
5. Update Job: `status = 'completed'`, `completed_at = now()`
6. Clean up entire temp directory (`shutil.rmtree`)

### `backend/app/export/`

#### `router.py` — Export API endpoints

**`POST /exports`** — Create export and trigger render
- Request body: `{"clip_id": UUID, "platform": "shorts"|"tiktok"|"reels"|"square"|"twitter"}`
- Validates: clip exists, belongs to user, clip status is `selected`
- Rate limit check: count user's exports in last 24h vs `render_rate_limit_free`
- Creates Export record with platform specs (aspect_ratio, resolution from specs.py)
- Creates Job record (type=`render`, status=`pending`)
- Enqueues `prepare_render_task`
- Returns: `{"export_id": UUID, "job_id": UUID, "status": "pending"}`

**`GET /exports/{export_id}`** — Get export status and download URL
- User-scoped (Export.user_id == current user)
- Returns: export details including download_url if rendered

**`GET /exports/clip/{clip_id}`** — List all exports for a clip
- User-scoped via clip ownership
- Returns: list of exports with status and download URLs

#### `schemas.py` — Pydantic models

- `ExportRequest`: clip_id (UUID), platform (Literal["shorts","tiktok","reels","square","twitter"])
- `ExportResponse`: id, clip_id, platform, aspect_ratio, resolution, status, job_id, download_url, created_at

## Database Changes

### New column on `clips` table

```python
face_track = Column(JSONB, nullable=True)
```

Format: `{"frames": [{"t": 0.0, "x": 540, "y": 360}, ...], "smoothed": true, "method": "mediapipe"}`

### New column on `exports` table

```python
status = Column(String(20), nullable=False, default="pending")
job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=True)
```

`Export.status` tracks per-export render lifecycle: `pending → rendering → rendered → failed`. This replaces mutating `Clip.status` per-export, which breaks when multiple exports exist for the same clip. `Clip.status` remains at `selected` throughout — only the Export tracks render progress.

`Export.job_id` links each export to its render Job for status derivation and pipeline coordination.

Add CHECK constraint: `status IN ('pending', 'rendering', 'rendered', 'failed')`.

### New column on `jobs` table

```python
render_context = Column(JSONB, nullable=True)
```

Stores pipeline state between steps: temp file paths, face track reference, platform specs.

### `Clip.rendered_s3_key` — not used by render pipeline

The existing `Clip.rendered_s3_key` column is NOT updated by the render pipeline. Per-export S3 keys live on `Export.s3_key`. The column remains for potential future use (e.g., a "primary" rendered version) but is not part of this implementation.

### Alembic migration

Single migration adds: `clips.face_track`, `exports.status`, `exports.job_id`, `jobs.render_context`. All nullable except `exports.status` (defaults to `pending`). No data backfill needed.

## Modified Files

- `backend/app/jobs/tasks.py` — Import and register the three render tasks (or keep them in `rendering/pipeline.py` and import into worker)
- `backend/app/jobs/worker.py` — Add `prepare_render_task`, `execute_render_task`, `upload_output_task` to `functions` list
- `backend/app/main.py` — Mount `export.router`
- `backend/requirements.txt` — Add `mediapipe`

## Error Handling

**Per-step failure:**
- Each step wraps work in try/except
- On failure: set `Job.status = 'failed'`, `Job.error_message = str(error)`, `Job.completed_at = now()`
- Set `Export.status = 'failed'` (NOT `Clip.status` — clip remains `selected` so user can retry)
- Clean up temp directory (`shutil.rmtree` the entire `/tmp/clipforge/render/{job_id}/` dir)
- Do NOT enqueue next step

**FFmpeg crash (execute_render):**
- Check return code from subprocess
- If non-zero: capture stderr, store in error_message
- Delete partial output file if it exists
- Common failures: codec not available, input file corrupt, disk full

**Retry strategy:**
- User-initiated retry only (no automatic retry in MVP)
- Retry creates a new Export + Job
- `prepare_render` reuses existing face_track if available
- No need to re-download if temp files still exist (but don't depend on it — always check)

**Temp file cleanup:**
- Each step cleans up on failure
- `upload_output_task` cleans up on success (final step)
- Safety net: update `_cleanup_old_temp_files()` in tasks.py to recursively sweep `/tmp/clipforge/` including `render/` subdirectories for entries >1hr old (use `shutil.rmtree` for directories, `os.remove` for files)

## Rate Limiting

- Enforced at `POST /exports` endpoint
- Query: `SELECT COUNT(*) FROM exports WHERE user_id = :uid AND created_at > now() - interval '24 hours'`
- Free tier limit: 10/day rolling window (from `config.render_rate_limit_free`)
- Return 429 with `{"detail": "Daily render limit reached (10/day). Upgrade for more."}` if exceeded
- Note: This is a rate limit (abuse prevention), not a billing quota. Billing quotas (Week 4 Stripe integration) will replace this with monthly credit-based limits.

## Frontend Changes

### `ExportPanel` component

Displayed on VideoPage for clips with status `selected`:
- Platform selector (5 options with icons/labels)
- "Export" button triggers `POST /exports`
- Shows JobProgress for active render job
- Shows download button with presigned URL on completion

### VideoPage updates

- Add ExportPanel below ClipAdjuster when a selected clip is chosen
- Show export history for the clip (list of completed exports with download links)

## Security

- All export queries scoped to `user_id`
- Download URLs are presigned S3 URLs (1 hour expiry)
- Rate limiting prevents abuse
- Input video validated before render (exists on S3, matches DB record)
- Rendered files stored at `renders/{user_id}/{export_id}.mp4` — user-scoped S3 path
- No direct bucket path exposure

## In-Browser Clip Preview

Per CLAUDE.md Week 3 item 20: "In-browser clip preview (before render — use native video seek, not server render)"

- Use HTML5 `<video>` element with `#t=start,end` media fragment
- Generate presigned URL for original video with 15-min expiry
- Seek to clip start_time, pause at end_time
- No server-side rendering needed for preview
- Optional: overlay crop rectangle on video to show reframe area (CSS overlay, not video processing)
