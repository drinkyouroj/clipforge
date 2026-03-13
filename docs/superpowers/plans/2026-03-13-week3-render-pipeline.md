# Week 3: Render Pipeline Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a three-step render pipeline that takes a selected clip + target platform, applies face-based reframing, burns in word-highlighted ASS captions, and produces a platform-spec'd MP4 ready for download via presigned URL.

**Architecture:** Three chained ARQ tasks (prepare_render → execute_render → upload_output) share state via a temp directory and a `render_context` JSONB field on the Job record. Each Export record represents one clip-platform combination. Face tracks are cached on the Clip for reuse across exports.

**Tech Stack:** FFmpeg (video processing), mediapipe (face detection), ASS subtitles (word-highlight captions), ARQ (async job queue), S3/R2 (output storage), FastAPI (export API), React (export UI)

**Spec:** `docs/superpowers/specs/2026-03-13-render-pipeline-design.md`

---

## File Structure

### New files

| File | Responsibility |
|------|---------------|
| `backend/app/rendering/__init__.py` | Package init |
| `backend/app/rendering/specs.py` | Platform spec lookup (resolution, FPS, max duration per platform) |
| `backend/app/rendering/captions.py` | Word timestamps → ASS subtitle file with per-word highlighting |
| `backend/app/rendering/reframe.py` | Mediapipe face detection, track smoothing, crop calculation |
| `backend/app/rendering/ffmpeg_cmd.py` | FFmpeg command assembly from specs + crop + captions |
| `backend/app/rendering/pipeline.py` | Three ARQ tasks: prepare, execute, upload |
| `backend/app/export/__init__.py` | Package init |
| `backend/app/export/router.py` | POST /exports, GET /exports/{id}, GET /exports/clip/{clip_id} |
| `backend/app/export/schemas.py` | ExportRequest, ExportResponse, ExportListResponse |
| `backend/tests/unit/test_specs.py` | Tests for platform spec lookup |
| `backend/tests/unit/test_captions.py` | Tests for ASS generation |
| `backend/tests/unit/test_reframe.py` | Tests for crop calculation + track smoothing |
| `backend/tests/unit/test_ffmpeg_cmd.py` | Tests for FFmpeg command assembly |
| `backend/tests/unit/test_exports.py` | Tests for export API endpoints |
| `frontend/src/components/ExportPanel/ExportPanel.tsx` | Platform selector + render trigger + download |
| `frontend/src/components/ClipPreview/ClipPreview.tsx` | In-browser video preview with seek |

### Modified files

| File | Changes |
|------|---------|
| `backend/app/db/models.py` | Add `Clip.face_track`, `Export.status`, `Export.job_id`, `Job.render_context` |
| `backend/app/jobs/tasks.py` | Update `_cleanup_old_temp_files()` for subdirectories |
| `backend/app/jobs/worker.py` | Register 3 render task functions |
| `backend/app/main.py` | Mount `export.router` |
| `backend/requirements.txt` | Add `mediapipe` |
| `frontend/src/pages/VideoPage.tsx` | Add ExportPanel + ClipPreview |
| `frontend/src/App.css` | Export panel + preview styles |

---

## Chunk 1: Foundation — DECISION doc, DB changes, platform specs

### Task 1: DECISION_007 — Render Pipeline (Adversarial Agent Protocol)

**Files:**
- Create: `docs/decisions/DECISION_007_render_pipeline.md`

- [ ] **Step 1: Write DECISION_007**

Write the DECISION doc following the ARCHITECT / ADVERSARY / JUDGE protocol. Content derives from the approved spec.

```markdown
# DECISION 007: Render Pipeline and FFmpeg Command Design

## ARCHITECT proposes:

### Three-Step Chained Pipeline
Render jobs use three chained ARQ tasks for granular retry:
1. `prepare_render` — download video from S3, run mediapipe face detection (cached on Clip), generate ASS captions
2. `execute_render` — assemble FFmpeg command per platform specs, run render
3. `upload_output` — upload to S3, generate presigned URL, update Export record

Steps share state via `/tmp/clipforge/render/{job_id}/` temp directory and `Job.render_context` JSONB.

### Export-Centric Model
One Export record per clip-platform combination. Export.status tracks render lifecycle (pending → rendering → rendered → failed). Clip.status remains `selected` throughout — no per-export mutation of clip state.

### Face Detection + Smart Crop
- mediapipe face detection on keyframes every 0.5s
- Smoothed face position track (moving average, window=15) stored as JSONB on Clip.face_track
- Reusable across multiple exports of same clip
- Fallback: center crop if no face detected
- Crop formulas: 9:16 = `crop=ih*(9/16):ih:smooth_x:0`, 1:1 = `crop=ih:ih:smooth_x:0`, 16:9 = scale only

### ASS Captions with Word Highlighting
- ASS/SSA format (not SRT) for per-word color timing
- Active word: yellow (\c&H0000FFFF&), inactive: white (\c&H00FFFFFF&)
- ~3-4 words per display line, split at pauses >0.5s
- Timestamps relative to 0 (not original video time) since FFmpeg -ss before -i resets timeline

### FFmpeg Command
```
ffmpeg -ss {start} -i {input} -t {duration} \
  -vf "crop=...,scale=...,ass={captions}" \
  -c:v libx264 -preset fast -crf 23 \
  -c:a aac -b:a 192k -ac 2 \
  -af loudnorm=I=-14:LRA=11:TP=-1.5 \
  -movflags +faststart -y {output}
```

### Platform Specs
| Platform | Aspect | Resolution | FPS | Max Duration |
|----------|--------|------------|-----|-------------|
| shorts | 9:16 | 1080x1920 | 30 | 60s |
| tiktok | 9:16 | 1080x1920 | 30 | 60s |
| reels | 9:16 | 1080x1920 | 30 | 90s |
| square | 1:1 | 1080x1080 | 30 | 60s |
| twitter | 16:9 | 1280x720 | 30 | 140s |

All: MP4 H.264, AAC 192kbps stereo, -14 LUFS loudness normalization, faststart.

## ADVERSARY attacks:

1. **FFmpeg crash leaves orphan temp files consuming disk.** If `execute_render` crashes mid-render, the partial output file (potentially GBs) sits in `/tmp/clipforge/render/{job_id}/` until someone notices. The existing cleanup only sweeps top-level files in `/tmp/clipforge/`, not subdirectories.

2. **Concurrent exports for same clip create face detection race condition.** If two exports are triggered simultaneously for the same clip and both see `face_track IS NULL`, they'll both run mediapipe. This wastes compute and could produce conflicting writes to the same JSONB column.

3. **Output file larger than input.** FFmpeg misconfiguration (wrong codec, no compression) could produce an output larger than the input segment. This silently wastes S3 storage and user bandwidth. No validation catches it.

4. **ASS subtitle non-ASCII corruption.** Word timestamps may contain em dashes, curly quotes, or non-Latin characters. ASS format uses backslash escape sequences that could collide with special characters, producing garbled captions.

5. **mediapipe not available in CI/production.** mediapipe has heavy native dependencies (OpenCV, TFLite). It may fail to install on Alpine-based Docker images or ARM architectures. No fallback if import fails.

## JUDGE decides:

**Green light with required changes:**

1. **Temp file cleanup — fix required.** Update `_cleanup_old_temp_files()` to recursively sweep subdirectories. Each pipeline step must also clean up on failure via `shutil.rmtree`. Both defenses.

2. **Face detection race — accept for MVP.** Concurrent exports for the same clip are an edge case (user would have to click two platforms within seconds). The duplicate work is harmless — both writes produce the same face track. If this becomes a problem post-launch, add a per-clip lock. Not worth the complexity now.

3. **Output size check — required.** `execute_render` must verify `output_size < 2 * input_segment_size`. If exceeded, fail with descriptive error. Simple to implement, catches real misconfiguration.

4. **ASS non-ASCII — handle in implementation.** Escape backslashes and braces in word text before inserting into ASS tags. Test with em dashes and curly quotes specifically.

5. **mediapipe availability — accept with fallback.** If mediapipe import fails, fall back to center crop. Log a warning. This lets the pipeline work in environments without mediapipe (dev, CI) while still producing usable output.

## Implementation notes:
- Export.status tracks render lifecycle, NOT Clip.status
- Export.job_id FK links to the render Job
- Clip.rendered_s3_key is NOT used by this pipeline (per-export keys on Export.s3_key)
- Caption timestamps rebased to 0 due to -ss input seeking
- Rate limit: 10 exports/day rolling window (abuse prevention, not billing)
```

- [ ] **Step 2: Commit DECISION_007**

```bash
git add docs/decisions/DECISION_007_render_pipeline.md
git commit -m "docs(decisions): add DECISION_007 render pipeline design"
```

---

### Task 2: Database model changes

**Files:**
- Modify: `backend/app/db/models.py`

- [ ] **Step 1: Write failing test for new columns**

Create `backend/tests/unit/test_render_models.py`:

```python
"""Tests for render pipeline model changes."""

from app.db.models import Clip, Export, Job


def test_clip_has_face_track_column():
    """Clip model has face_track JSONB column."""
    assert hasattr(Clip, "face_track")


def test_export_has_status_column():
    """Export model has status column with default."""
    assert hasattr(Export, "status")


def test_export_has_job_id_column():
    """Export model has job_id FK column."""
    assert hasattr(Export, "job_id")


def test_job_has_render_context_column():
    """Job model has render_context JSONB column."""
    assert hasattr(Job, "render_context")


async def test_create_export_with_status(db_session):
    """Can create an Export with status and job_id."""
    from app.db.models import User, Video, Transcript, Clip, Job, Export
    from datetime import datetime, timezone

    user = User(
        email="renderuser@example.com",
        hashed_password="hashed",
        tos_accepted_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    await db_session.flush()

    video = Video(
        user_id=user.id,
        original_filename="test.mp4",
        s3_key=f"uploads/{user.id}/test.mp4",
        file_size=1024,
        duration=300.0,
        status="ready",
    )
    db_session.add(video)
    await db_session.flush()

    transcript = Transcript(
        video_id=video.id,
        content="hello world",
        word_timestamps=[],
        language="en",
    )
    db_session.add(transcript)
    await db_session.flush()

    clip = Clip(
        video_id=video.id,
        transcript_id=transcript.id,
        start_time=10.0,
        end_time=50.0,
        duration=40.0,
        virality_score=85,
        status="selected",
        face_track={"frames": [{"t": 0.0, "x": 540, "y": 360}], "smoothed": True},
    )
    db_session.add(clip)
    await db_session.flush()

    job = Job(
        user_id=user.id,
        video_id=video.id,
        job_type="render",
        status="pending",
        render_context={"temp_dir": "/tmp/clipforge/render/test"},
    )
    db_session.add(job)
    await db_session.flush()

    export = Export(
        clip_id=clip.id,
        user_id=user.id,
        platform="shorts",
        aspect_ratio="9:16",
        resolution="1080x1920",
        status="pending",
        job_id=job.id,
    )
    db_session.add(export)
    await db_session.commit()
    await db_session.refresh(export)

    assert export.status == "pending"
    assert export.job_id == job.id
    assert clip.face_track["smoothed"] is True
    assert job.render_context["temp_dir"] == "/tmp/clipforge/render/test"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/unit/test_render_models.py -v`
Expected: FAIL — Clip has no `face_track`, Export has no `status`/`job_id`, Job has no `render_context`

- [ ] **Step 3: Add columns to models.py**

In `backend/app/db/models.py`, add to the `Clip` class (after `rendered_s3_key`):

```python
    face_track = Column(JSONB, nullable=True)
```

Add to the `Export` class (after `clip_id`):

```python
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=True)
    status = Column(String(20), nullable=False, default="pending")
```

Update the existing `Export.__table_args__` tuple to add a CHECK constraint (the `Index` already exists — keep it):

```python
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'rendering', 'rendered', 'failed')",
            name="ck_exports_status",
        ),
        Index("ix_exports_user_created", "user_id", "created_at"),
    )
```

Add a `job` relationship to Export:

```python
    job = relationship("Job", backref="export")
```

Add to the `Job` class (after `completed_at`):

```python
    render_context = Column(JSONB, nullable=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/unit/test_render_models.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run all existing tests to check no regressions**

Run: `cd backend && python -m pytest tests/ -v`
Expected: ALL PASS (60 existing + new tests)

- [ ] **Step 6: Commit model changes**

```bash
git add backend/app/db/models.py backend/tests/unit/test_render_models.py
git commit -m "feat(db): add render pipeline columns — face_track, export status/job_id, render_context"
```

- [ ] **Step 7: Generate Alembic migration**

Note: Tests pass without a migration because the test fixture uses `Base.metadata.create_all` (see `conftest.py`). But a migration is required for the real database.

```bash
cd backend && alembic revision --autogenerate -m "add render pipeline columns"
```

Review the generated migration to verify it adds:
- `clips.face_track` (JSONB, nullable)
- `exports.status` (VARCHAR(20), NOT NULL, default 'pending', CHECK constraint)
- `exports.job_id` (UUID, FK to jobs.id, nullable)
- `jobs.render_context` (JSONB, nullable)

- [ ] **Step 8: Commit migration**

```bash
git add backend/app/db/migrations/versions/
git commit -m "feat(db): add alembic migration for render pipeline columns"
```

---

### Task 3: Platform specs module

**Files:**
- Create: `backend/app/rendering/__init__.py`
- Create: `backend/app/rendering/specs.py`
- Create: `backend/tests/unit/test_specs.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/unit/test_specs.py`:

```python
"""Tests for platform export specifications."""

from app.rendering.specs import get_platform_spec, PLATFORMS


def test_all_five_platforms_defined():
    assert set(PLATFORMS.keys()) == {"shorts", "tiktok", "reels", "square", "twitter"}


def test_shorts_spec():
    spec = get_platform_spec("shorts")
    assert spec["aspect_ratio"] == "9:16"
    assert spec["width"] == 1080
    assert spec["height"] == 1920
    assert spec["fps"] == 30
    assert spec["max_duration"] == 60


def test_square_spec():
    spec = get_platform_spec("square")
    assert spec["aspect_ratio"] == "1:1"
    assert spec["width"] == 1080
    assert spec["height"] == 1080


def test_twitter_spec():
    spec = get_platform_spec("twitter")
    assert spec["aspect_ratio"] == "16:9"
    assert spec["width"] == 1280
    assert spec["height"] == 720
    assert spec["max_duration"] == 140


def test_all_specs_have_required_fields():
    required = {"aspect_ratio", "width", "height", "fps", "max_duration", "codec", "audio_bitrate"}
    for key, spec in PLATFORMS.items():
        for field in required:
            assert field in spec, f"Platform '{key}' missing field '{field}'"


def test_invalid_platform_raises():
    import pytest
    with pytest.raises(ValueError, match="Unknown platform"):
        get_platform_spec("myspace")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/unit/test_specs.py -v`
Expected: FAIL — ModuleNotFoundError: No module named 'app.rendering'

- [ ] **Step 3: Implement specs module**

Create `backend/app/rendering/__init__.py` (empty file).

Create `backend/app/rendering/specs.py`:

```python
"""Platform export specifications per CLAUDE.md."""

PLATFORMS = {
    "shorts": {
        "name": "YouTube Shorts",
        "aspect_ratio": "9:16",
        "width": 1080,
        "height": 1920,
        "fps": 30,
        "max_duration": 60,
        "codec": "libx264",
        "audio_bitrate": "192k",
    },
    "tiktok": {
        "name": "TikTok",
        "aspect_ratio": "9:16",
        "width": 1080,
        "height": 1920,
        "fps": 30,
        "max_duration": 60,
        "codec": "libx264",
        "audio_bitrate": "192k",
    },
    "reels": {
        "name": "Instagram Reels",
        "aspect_ratio": "9:16",
        "width": 1080,
        "height": 1920,
        "fps": 30,
        "max_duration": 90,
        "codec": "libx264",
        "audio_bitrate": "192k",
    },
    "square": {
        "name": "Instagram Square",
        "aspect_ratio": "1:1",
        "width": 1080,
        "height": 1080,
        "fps": 30,
        "max_duration": 60,
        "codec": "libx264",
        "audio_bitrate": "192k",
    },
    "twitter": {
        "name": "X (Twitter)",
        "aspect_ratio": "16:9",
        "width": 1280,
        "height": 720,
        "fps": 30,
        "max_duration": 140,
        "codec": "libx264",
        "audio_bitrate": "192k",
    },
}


def get_platform_spec(platform: str) -> dict:
    """Get export specifications for a platform.

    Args:
        platform: One of 'shorts', 'tiktok', 'reels', 'square', 'twitter'

    Returns:
        Dict with aspect_ratio, width, height, fps, max_duration, codec, audio_bitrate

    Raises:
        ValueError: If platform is not recognized
    """
    if platform not in PLATFORMS:
        raise ValueError(f"Unknown platform: '{platform}'. Must be one of: {list(PLATFORMS.keys())}")
    return PLATFORMS[platform]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/unit/test_specs.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/rendering/__init__.py backend/app/rendering/specs.py backend/tests/unit/test_specs.py
git commit -m "feat(render): add platform export specifications module"
```

---

### Task 4: Update temp file cleanup for subdirectories

**Files:**
- Modify: `backend/app/jobs/tasks.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/unit/test_temp_cleanup.py`:

```python
"""Tests for temp file cleanup handling subdirectories."""

import os
import time
from unittest.mock import patch

from app.jobs.tasks import _cleanup_old_temp_files, TEMP_DIR


def test_cleanup_removes_old_subdirectories(tmp_path):
    """Cleanup sweeps old job dirs inside render/, even if render/ itself is recent."""
    with patch("app.jobs.tasks.TEMP_DIR", str(tmp_path)):
        # Create render/ parent (recent — new jobs keep this fresh)
        render_dir = tmp_path / "render"
        render_dir.mkdir()

        # Create an old job subdirectory inside render/
        old_dir = render_dir / "old-job-id"
        old_dir.mkdir()
        old_file = old_dir / "input.mp4"
        old_file.write_text("data")

        # Make job dir appear old (>1hr) but NOT the parent render/ dir
        old_time = time.time() - 7200
        os.utime(str(old_dir), (old_time, old_time))
        # render/ dir stays recent (default mtime = now)

        # Create a recent file at top level (should NOT be deleted)
        recent = tmp_path / "recent.mp4"
        recent.write_text("fresh")

        _cleanup_old_temp_files()

        assert not old_dir.exists(), "Old render job subdirectory should be removed"
        assert recent.exists(), "Recent files should not be removed"
        assert render_dir.exists(), "render/ parent should remain (may have active jobs)"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/unit/test_temp_cleanup.py -v`
Expected: FAIL — old subdirectory still exists (current cleanup only handles flat files)

- [ ] **Step 3: Update cleanup function**

In `backend/app/jobs/tasks.py`, replace `_cleanup_old_temp_files`:

```python
def _cleanup_old_temp_files():
    """Sweep /tmp/clipforge/ for files and directories older than 1 hour.

    Walks two levels deep to handle render/{job_id}/ subdirectories,
    since the render/ parent dir mtime refreshes when new jobs are created.
    """
    import shutil

    if not os.path.exists(TEMP_DIR):
        return
    now = datetime.now(timezone.utc).timestamp()
    for entry in os.listdir(TEMP_DIR):
        path = os.path.join(TEMP_DIR, entry)
        try:
            if os.path.isdir(path):
                # Walk into subdirectories (e.g., render/) to find old job dirs
                for sub_entry in os.listdir(path):
                    sub_path = os.path.join(path, sub_entry)
                    try:
                        if (now - os.path.getmtime(sub_path)) > 3600:
                            if os.path.isdir(sub_path):
                                shutil.rmtree(sub_path)
                            else:
                                os.unlink(sub_path)
                    except OSError:
                        pass
                # Remove parent dir if now empty
                try:
                    if not os.listdir(path):
                        os.rmdir(path)
                except OSError:
                    pass
            elif os.path.isfile(path) and (now - os.path.getmtime(path)) > 3600:
                os.unlink(path)
        except OSError:
            pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/unit/test_temp_cleanup.py -v`
Expected: PASS

- [ ] **Step 5: Run all tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/jobs/tasks.py backend/tests/unit/test_temp_cleanup.py
git commit -m "fix(jobs): update temp cleanup to handle render subdirectories"
```

---

## Chunk 2: Rendering Modules — captions, reframe, FFmpeg command

### Task 5: ASS caption generator

**Files:**
- Create: `backend/app/rendering/captions.py`
- Create: `backend/tests/unit/test_captions.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/unit/test_captions.py`:

```python
"""Tests for ASS subtitle generation with word highlighting."""

from app.rendering.captions import generate_ass_captions, group_words_into_lines


def test_group_words_into_lines_basic():
    words = [
        {"word": "hello", "start": 0.0, "end": 0.3},
        {"word": "world", "start": 0.3, "end": 0.6},
        {"word": "this", "start": 0.6, "end": 0.9},
        {"word": "is", "start": 0.9, "end": 1.0},
        {"word": "a", "start": 1.0, "end": 1.1},
        {"word": "test", "start": 1.1, "end": 1.4},
    ]
    lines = group_words_into_lines(words, max_words=3)
    assert len(lines) == 2
    assert len(lines[0]) == 3  # hello world this
    assert len(lines[1]) == 3  # is a test


def test_group_words_splits_at_long_pause():
    words = [
        {"word": "hello", "start": 0.0, "end": 0.3},
        {"word": "world", "start": 0.3, "end": 0.6},
        {"word": "goodbye", "start": 2.0, "end": 2.3},  # >0.5s pause
    ]
    lines = group_words_into_lines(words, max_words=4)
    assert len(lines) == 2  # Split at the pause


def test_group_words_empty():
    lines = group_words_into_lines([], max_words=3)
    assert lines == []


def test_generate_ass_header():
    words = [{"word": "hello", "start": 0.0, "end": 0.5}]
    ass = generate_ass_captions(words, clip_start_time=0.0)
    assert "[Script Info]" in ass
    assert "[V4+ Styles]" in ass
    assert "Style: Default" in ass
    assert "Arial" in ass


def test_generate_ass_dialogue_events():
    words = [
        {"word": "hello", "start": 10.0, "end": 10.3},
        {"word": "world", "start": 10.3, "end": 10.6},
        {"word": "test", "start": 10.6, "end": 10.9},
    ]
    ass = generate_ass_captions(words, clip_start_time=10.0)
    assert "[Events]" in ass
    assert "Dialogue:" in ass


def test_caption_timestamps_rebased_to_zero():
    """Timestamps must be relative to 0, not original video time."""
    words = [
        {"word": "hello", "start": 120.0, "end": 120.5},
        {"word": "world", "start": 120.5, "end": 121.0},
    ]
    ass = generate_ass_captions(words, clip_start_time=120.0)
    # Should NOT contain 2:00 timestamps, should be near 0:00
    assert "0:00:00" in ass or "0:00:01" in ass


def test_caption_highlight_colors():
    """Active word should use yellow, inactive white."""
    words = [
        {"word": "hello", "start": 0.0, "end": 0.5},
        {"word": "world", "start": 0.5, "end": 1.0},
    ]
    ass = generate_ass_captions(words, clip_start_time=0.0)
    assert "\\c&H0000FFFF&" in ass  # yellow (active)
    assert "\\c&H00FFFFFF&" in ass  # white (inactive)


def test_caption_escapes_special_characters():
    """Non-ASCII and ASS-special chars should not corrupt output."""
    words = [
        {"word": "it\u2019s", "start": 0.0, "end": 0.3},  # curly apostrophe
        {"word": "\u2014", "start": 0.3, "end": 0.5},  # em dash
        {"word": "caf\u00e9", "start": 0.5, "end": 0.8},  # accented char
    ]
    ass = generate_ass_captions(words, clip_start_time=0.0)
    assert "Dialogue:" in ass  # Should not crash
    # Backslashes in words should be escaped
    assert "\u2019" in ass or "'" in ass
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/unit/test_captions.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: Implement captions module**

Create `backend/app/rendering/captions.py`:

```python
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

        line_start = line_words[0]["start"]
        line_end = line_words[-1]["end"]
        start_ts = _format_ass_time(line_start)
        end_ts = _format_ass_time(line_end)

        # Build text with per-word highlighting
        # For each moment in time, one word is "active" (yellow), rest are white
        # We create one dialogue event per word-highlight phase
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/unit/test_captions.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/rendering/captions.py backend/tests/unit/test_captions.py
git commit -m "feat(captions): add ASS subtitle generator with per-word highlighting"
```

---

### Task 6: Face detection + reframe (crop calculation)

**Files:**
- Create: `backend/app/rendering/reframe.py`
- Create: `backend/tests/unit/test_reframe.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/unit/test_reframe.py`:

```python
"""Tests for face detection and smart crop calculation."""

from app.rendering.reframe import (
    smooth_face_track,
    calculate_crop,
    compute_crop_params,
)


def test_smooth_face_track_basic():
    """Moving average smoothing should reduce jitter."""
    track = [
        {"t": 0.0, "x": 500, "y": 360},
        {"t": 0.5, "x": 520, "y": 360},
        {"t": 1.0, "x": 480, "y": 360},
        {"t": 1.5, "x": 510, "y": 360},
        {"t": 2.0, "x": 490, "y": 360},
    ]
    smoothed = smooth_face_track(track, window=3)
    assert len(smoothed) == 5
    # Smoothed values should be closer to the mean
    assert all("x" in f and "y" in f and "t" in f for f in smoothed)


def test_smooth_face_track_single_point():
    track = [{"t": 0.0, "x": 500, "y": 360}]
    smoothed = smooth_face_track(track, window=3)
    assert len(smoothed) == 1
    assert smoothed[0]["x"] == 500


def test_smooth_face_track_empty():
    smoothed = smooth_face_track([], window=3)
    assert smoothed == []


def test_calculate_crop_9_16():
    """9:16 crop: full height, width = height * 9/16, centered on face."""
    crop = calculate_crop(
        video_width=1920, video_height=1080,
        face_x=960, aspect_ratio="9:16"
    )
    assert crop["crop_h"] == 1080  # full height
    assert crop["crop_w"] == 607   # 1080 * 9 / 16 = 607.5 → 607
    assert crop["crop_y"] == 0     # top-aligned


def test_calculate_crop_1_1():
    """1:1 crop: full height, width = height, centered on face."""
    crop = calculate_crop(
        video_width=1920, video_height=1080,
        face_x=960, aspect_ratio="1:1"
    )
    assert crop["crop_h"] == 1080
    assert crop["crop_w"] == 1080


def test_calculate_crop_16_9():
    """16:9: no crop needed, returns full frame dimensions."""
    crop = calculate_crop(
        video_width=1920, video_height=1080,
        face_x=960, aspect_ratio="16:9"
    )
    assert crop["crop_w"] == 1920
    assert crop["crop_h"] == 1080
    assert crop["crop_x"] == 0
    assert crop["crop_y"] == 0


def test_calculate_crop_clamps_to_bounds():
    """Crop X should not go negative or exceed frame width."""
    crop = calculate_crop(
        video_width=1920, video_height=1080,
        face_x=50, aspect_ratio="9:16"  # Face near left edge
    )
    assert crop["crop_x"] >= 0
    assert crop["crop_x"] + crop["crop_w"] <= 1920


def test_compute_crop_params_center_fallback():
    """When face_track is None, use center crop."""
    params = compute_crop_params(
        face_track=None,
        video_width=1920, video_height=1080,
        aspect_ratio="9:16",
    )
    # Should center: crop_x = (1920 - crop_w) / 2
    expected_w = int(1080 * 9 / 16)
    assert params["crop_x"] == (1920 - expected_w) // 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/unit/test_reframe.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: Implement reframe module**

Create `backend/app/rendering/reframe.py`:

```python
"""Face detection, track smoothing, and crop calculation for smart reframing."""

import logging
import os
import subprocess
import json
import tempfile

logger = logging.getLogger(__name__)

# Aspect ratio to width/height multiplier (relative to video height)
ASPECT_RATIOS = {
    "9:16": 9 / 16,
    "1:1": 1.0,
    "16:9": 16 / 9,
}


def smooth_face_track(track: list[dict], window: int = 15) -> list[dict]:
    """Apply moving average smoothing to face position track.

    Args:
        track: List of {"t": float, "x": int, "y": int}
        window: Smoothing window size

    Returns:
        Smoothed track with same structure
    """
    if len(track) <= 1:
        return track

    smoothed = []
    half = window // 2
    for i in range(len(track)):
        start = max(0, i - half)
        end = min(len(track), i + half + 1)
        avg_x = int(sum(t["x"] for t in track[start:end]) / (end - start))
        avg_y = int(sum(t["y"] for t in track[start:end]) / (end - start))
        smoothed.append({"t": track[i]["t"], "x": avg_x, "y": avg_y})

    return smoothed


def calculate_crop(
    video_width: int, video_height: int,
    face_x: int, aspect_ratio: str,
) -> dict:
    """Calculate crop parameters for a given aspect ratio centered on face_x.

    Args:
        video_width: Source video width in pixels
        video_height: Source video height in pixels
        face_x: Horizontal center of face in pixels
        aspect_ratio: Target aspect ratio ('9:16', '1:1', '16:9')

    Returns:
        Dict with crop_w, crop_h, crop_x, crop_y
    """
    if aspect_ratio == "16:9":
        return {
            "crop_w": video_width,
            "crop_h": video_height,
            "crop_x": 0,
            "crop_y": 0,
        }

    ratio = ASPECT_RATIOS[aspect_ratio]
    crop_h = video_height
    crop_w = int(video_height * ratio)

    # Clamp crop width to video width
    crop_w = min(crop_w, video_width)

    # Center crop on face_x
    crop_x = face_x - crop_w // 2

    # Clamp to frame bounds
    crop_x = max(0, crop_x)
    crop_x = min(crop_x, video_width - crop_w)

    return {
        "crop_w": crop_w,
        "crop_h": crop_h,
        "crop_x": crop_x,
        "crop_y": 0,
    }


def compute_crop_params(
    face_track: dict | None,
    video_width: int, video_height: int,
    aspect_ratio: str,
) -> dict:
    """Compute crop parameters from face track or center fallback.

    Args:
        face_track: {"frames": [...], "smoothed": bool} or None
        video_width: Source width
        video_height: Source height
        aspect_ratio: Target aspect ratio

    Returns:
        Dict with crop_w, crop_h, crop_x, crop_y (using median face position)
    """
    if face_track and face_track.get("frames"):
        frames = face_track["frames"]
        median_x = sorted(f["x"] for f in frames)[len(frames) // 2]
    else:
        # Center fallback
        median_x = video_width // 2

    return calculate_crop(video_width, video_height, median_x, aspect_ratio)


def extract_keyframes(video_path: str, start_time: float, duration: float, interval: float = 0.5) -> list[str]:
    """Extract keyframes from video segment using FFmpeg.

    Args:
        video_path: Path to video file
        start_time: Start time in seconds
        duration: Duration in seconds
        interval: Seconds between keyframes

    Returns:
        List of paths to extracted frame images
    """
    output_dir = tempfile.mkdtemp(prefix="clipforge_frames_")
    output_pattern = os.path.join(output_dir, "frame_%04d.jpg")

    subprocess.run(
        [
            "ffmpeg", "-ss", str(start_time),
            "-i", video_path,
            "-t", str(duration),
            "-vf", f"fps=1/{interval}",
            "-q:v", "2",
            "-y", output_pattern,
        ],
        capture_output=True, check=True, timeout=120,
    )

    frames = sorted(
        os.path.join(output_dir, f)
        for f in os.listdir(output_dir)
        if f.endswith(".jpg")
    )
    return frames


def detect_faces_in_frames(frame_paths: list[str], interval: float = 0.5) -> list[dict]:
    """Run face detection on extracted frames.

    Uses mediapipe if available, otherwise returns empty list (center crop fallback).

    Args:
        frame_paths: Paths to frame images
        interval: Time between frames in seconds

    Returns:
        List of {"t": float, "x": int, "y": int} for frames where face was detected
    """
    try:
        import mediapipe as mp
    except ImportError:
        logger.warning("mediapipe not available — falling back to center crop")
        return []

    face_detection = mp.solutions.face_detection.FaceDetection(
        model_selection=1, min_detection_confidence=0.5
    )

    import cv2

    track = []
    for i, path in enumerate(frame_paths):
        image = cv2.imread(path)
        if image is None:
            continue

        h, w = image.shape[:2]
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        results = face_detection.process(rgb)

        if results.detections:
            # Use first detected face
            bbox = results.detections[0].location_data.relative_bounding_box
            center_x = int((bbox.xmin + bbox.width / 2) * w)
            center_y = int((bbox.ymin + bbox.height / 2) * h)
            track.append({"t": i * interval, "x": center_x, "y": center_y})

    face_detection.close()
    return track


def build_face_track(
    video_path: str, start_time: float, duration: float
) -> dict:
    """Build a complete face track for a clip segment.

    Returns:
        {"frames": [...], "smoothed": true, "method": "mediapipe"|"center"}
    """
    frames = extract_keyframes(video_path, start_time, duration)

    try:
        track = detect_faces_in_frames(frames)
    finally:
        # Clean up frame images
        import shutil
        if frames:
            frame_dir = os.path.dirname(frames[0])
            shutil.rmtree(frame_dir, ignore_errors=True)

    if not track:
        return {"frames": [], "smoothed": False, "method": "center"}

    smoothed = smooth_face_track(track, window=15)
    return {"frames": smoothed, "smoothed": True, "method": "mediapipe"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/unit/test_reframe.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/rendering/reframe.py backend/tests/unit/test_reframe.py
git commit -m "feat(render): add face detection reframe with crop calculation and track smoothing"
```

---

### Task 7: FFmpeg command assembly

**Files:**
- Create: `backend/app/rendering/ffmpeg_cmd.py`
- Create: `backend/tests/unit/test_ffmpeg_cmd.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/unit/test_ffmpeg_cmd.py`:

```python
"""Tests for FFmpeg command assembly."""

from app.rendering.ffmpeg_cmd import build_ffmpeg_command


def test_basic_9_16_command():
    cmd = build_ffmpeg_command(
        input_path="/tmp/input.mp4",
        output_path="/tmp/output.mp4",
        start_time=10.0,
        duration=30.0,
        crop={"crop_w": 607, "crop_h": 1080, "crop_x": 200, "crop_y": 0},
        width=1080, height=1920,
        aspect_ratio="9:16",
        ass_path="/tmp/captions.ass",
    )
    assert cmd[0] == "ffmpeg"
    assert "-ss" in cmd
    assert "10.0" in cmd or "10" in cmd
    assert "-t" in cmd
    assert "-r" in cmd  # FPS flag
    assert "30" in cmd
    assert "-movflags" in cmd
    assert "+faststart" in cmd
    assert "-y" in cmd
    assert "/tmp/output.mp4" == cmd[-1]


def test_video_filter_chain_with_crop():
    cmd = build_ffmpeg_command(
        input_path="/tmp/input.mp4",
        output_path="/tmp/output.mp4",
        start_time=0.0, duration=30.0,
        crop={"crop_w": 607, "crop_h": 1080, "crop_x": 200, "crop_y": 0},
        width=1080, height=1920,
        aspect_ratio="9:16",
        ass_path="/tmp/captions.ass",
    )
    # Find the -vf argument
    vf_idx = cmd.index("-vf")
    vf_value = cmd[vf_idx + 1]
    assert "crop=607:1080:200:0" in vf_value
    assert "scale=1080:1920" in vf_value
    assert "ass=/tmp/captions.ass" in vf_value


def test_16_9_no_crop():
    """16:9 should not include crop filter (full frame)."""
    cmd = build_ffmpeg_command(
        input_path="/tmp/input.mp4",
        output_path="/tmp/output.mp4",
        start_time=0.0, duration=30.0,
        crop={"crop_w": 1920, "crop_h": 1080, "crop_x": 0, "crop_y": 0},
        width=1280, height=720,
        aspect_ratio="16:9",
        ass_path="/tmp/captions.ass",
    )
    vf_idx = cmd.index("-vf")
    vf_value = cmd[vf_idx + 1]
    assert "crop=" not in vf_value
    assert "scale=1280:720" in vf_value


def test_audio_settings():
    cmd = build_ffmpeg_command(
        input_path="/tmp/input.mp4",
        output_path="/tmp/output.mp4",
        start_time=0.0, duration=30.0,
        crop={"crop_w": 607, "crop_h": 1080, "crop_x": 200, "crop_y": 0},
        width=1080, height=1920,
        aspect_ratio="9:16",
        ass_path="/tmp/captions.ass",
    )
    assert "-c:a" in cmd
    assert "aac" in cmd
    assert "-b:a" in cmd
    assert "192k" in cmd
    assert "-af" in cmd
    # Check loudnorm filter
    af_idx = cmd.index("-af")
    assert "loudnorm" in cmd[af_idx + 1]
    assert "I=-14" in cmd[af_idx + 1]


def test_no_captions():
    """Command without captions should omit ass filter."""
    cmd = build_ffmpeg_command(
        input_path="/tmp/input.mp4",
        output_path="/tmp/output.mp4",
        start_time=0.0, duration=30.0,
        crop={"crop_w": 607, "crop_h": 1080, "crop_x": 200, "crop_y": 0},
        width=1080, height=1920,
        aspect_ratio="9:16",
        ass_path=None,
    )
    vf_idx = cmd.index("-vf")
    vf_value = cmd[vf_idx + 1]
    assert "ass=" not in vf_value
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/unit/test_ffmpeg_cmd.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: Implement FFmpeg command builder**

Create `backend/app/rendering/ffmpeg_cmd.py`:

```python
"""FFmpeg command assembly for clip rendering."""


def build_ffmpeg_command(
    input_path: str,
    output_path: str,
    start_time: float,
    duration: float,
    crop: dict,
    width: int,
    height: int,
    fps: int = 30,
    aspect_ratio: str = "9:16",
    ass_path: str | None = None,
) -> list[str]:
    """Build FFmpeg command for rendering a clip.

    Args:
        input_path: Path to input video file
        output_path: Path for output MP4
        start_time: Seek position in input video (seconds)
        duration: Clip duration (seconds)
        crop: Dict with crop_w, crop_h, crop_x, crop_y
        width: Target output width
        height: Target output height
        fps: Target output FPS (default 30)
        aspect_ratio: Target aspect ratio (used to detect 16:9 no-crop case)
        ass_path: Path to ASS subtitle file (None to skip captions)

    Returns:
        FFmpeg command as list of strings for subprocess
    """
    # Video filter chain
    vf_parts = []

    # Crop — skip for 16:9 (full frame passthrough, just scale)
    if aspect_ratio != "16:9":
        vf_parts.append(
            f"crop={crop['crop_w']}:{crop['crop_h']}:{crop['crop_x']}:{crop['crop_y']}"
        )

    # Scale to target resolution
    vf_parts.append(f"scale={width}:{height}")

    # Captions
    if ass_path:
        vf_parts.append(f"ass={ass_path}")

    vf_chain = ",".join(vf_parts)

    cmd = [
        "ffmpeg",
        "-ss", str(start_time),
        "-i", input_path,
        "-t", str(duration),
        "-vf", vf_chain,
        "-r", str(fps),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ac", "2",
        "-af", "loudnorm=I=-14:LRA=11:TP=-1.5",
        "-movflags", "+faststart",
        "-y",
        output_path,
    ]

    return cmd
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/unit/test_ffmpeg_cmd.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/rendering/ffmpeg_cmd.py backend/tests/unit/test_ffmpeg_cmd.py
git commit -m "feat(render): add FFmpeg command assembly with crop, scale, captions, and loudnorm"
```

---

## Chunk 3: Pipeline Tasks + Export API

### Task 8: Render pipeline tasks (three-step chain)

**Files:**
- Create: `backend/app/rendering/pipeline.py`

This task creates the three ARQ tasks. They are tested via mock-based tests alongside the export API (Task 10), since they require full DB + S3 + FFmpeg integration.

- [ ] **Step 1: Implement pipeline module**

Create `backend/app/rendering/pipeline.py`:

```python
"""Three-step render pipeline: prepare → execute → upload."""

import json
import logging
import os
import shutil
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.config import settings
from app.db.models import Clip, Export, Job, Transcript, Video
from app.videos.storage import download_from_s3, upload_file_to_s3, generate_presigned_url

logger = logging.getLogger(__name__)

RENDER_TEMP_BASE = "/tmp/clipforge/render"


async def _get_db_session() -> AsyncSession:
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return session_factory()


def _get_temp_dir(job_id: str) -> str:
    path = os.path.join(RENDER_TEMP_BASE, job_id)
    os.makedirs(path, exist_ok=True)
    return path


def _cleanup_temp_dir(job_id: str):
    path = os.path.join(RENDER_TEMP_BASE, job_id)
    if os.path.exists(path):
        shutil.rmtree(path, ignore_errors=True)


async def _fail_export(db: AsyncSession, export: Export, job: Job, error: str, job_id_str: str):
    """Mark export and job as failed, clean up."""
    job.status = "failed"
    job.error_message = str(error)[:500]
    job.completed_at = datetime.now(timezone.utc)
    export.status = "failed"
    await db.commit()
    _cleanup_temp_dir(job_id_str)


async def prepare_render_task(ctx, export_id: str):
    """Step 1: Download video, run face detection, generate ASS captions."""
    from app.rendering.reframe import build_face_track
    from app.rendering.captions import generate_ass_captions

    db = await _get_db_session()
    try:
        exp_uuid = UUID(export_id)

        # Load export + job + clip + video + transcript
        export_result = await db.execute(
            select(Export).where(Export.id == exp_uuid)
        )
        export = export_result.scalar_one_or_none()
        if not export:
            return

        job_result = await db.execute(select(Job).where(Job.id == export.job_id))
        job = job_result.scalar_one_or_none()
        if not job:
            return

        clip_result = await db.execute(select(Clip).where(Clip.id == export.clip_id))
        clip = clip_result.scalar_one_or_none()

        video_result = await db.execute(select(Video).where(Video.id == clip.video_id))
        video = video_result.scalar_one_or_none()

        transcript_result = await db.execute(
            select(Transcript).where(Transcript.video_id == video.id)
        )
        transcript = transcript_result.scalar_one_or_none()

        # Update status
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        export.status = "rendering"
        await db.commit()

        job_id_str = str(job.id)
        temp_dir = _get_temp_dir(job_id_str)

        # Download video
        input_path = os.path.join(temp_dir, "input.mp4")
        await download_from_s3(video.s3_key, input_path)

        if not os.path.exists(input_path):
            await _fail_export(db, export, job, "Failed to download video from S3", job_id_str)
            return

        # Face detection (reuse cached track if available)
        if clip.face_track is None or not clip.face_track.get("frames"):
            face_track = build_face_track(input_path, clip.start_time, clip.duration)
            clip.face_track = face_track
            await db.commit()

        # Generate ASS captions (pass output resolution for correct PlayRes)
        from app.rendering.specs import get_platform_spec
        spec = get_platform_spec(export.platform)

        word_timestamps = transcript.word_timestamps if transcript else []
        ass_content = generate_ass_captions(
            word_timestamps, clip_start_time=clip.start_time,
            play_res_x=spec["width"], play_res_y=spec["height"],
        )
        ass_path = os.path.join(temp_dir, "captions.ass")
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(ass_content)

        # Store render context
        job.render_context = {
            "temp_dir": temp_dir,
            "input_path": input_path,
            "ass_path": ass_path,
            "export_id": export_id,
        }
        await db.commit()

        # Enqueue next step
        from arq import create_pool
        from arq.connections import RedisSettings

        pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        await pool.enqueue_job("execute_render_task", export_id)
        await pool.close()

    except Exception as e:
        try:
            export_result = await db.execute(select(Export).where(Export.id == UUID(export_id)))
            export = export_result.scalar_one_or_none()
            job_result = await db.execute(select(Job).where(Job.id == export.job_id)) if export else None
            job = job_result.scalar_one_or_none() if job_result else None
            if export and job:
                await _fail_export(db, export, job, str(e), str(job.id))
        except Exception:
            pass
        raise
    finally:
        await db.close()


async def execute_render_task(ctx, export_id: str):
    """Step 2: Build and run FFmpeg command."""
    import asyncio
    from app.rendering.ffmpeg_cmd import build_ffmpeg_command
    from app.rendering.reframe import compute_crop_params
    from app.rendering.specs import get_platform_spec

    db = await _get_db_session()
    try:
        exp_uuid = UUID(export_id)

        export_result = await db.execute(select(Export).where(Export.id == exp_uuid))
        export = export_result.scalar_one_or_none()
        if not export:
            return

        job_result = await db.execute(select(Job).where(Job.id == export.job_id))
        job = job_result.scalar_one_or_none()
        if not job or not job.render_context:
            return

        clip_result = await db.execute(select(Clip).where(Clip.id == export.clip_id))
        clip = clip_result.scalar_one_or_none()

        video_result = await db.execute(select(Video).where(Video.id == clip.video_id))
        video = video_result.scalar_one_or_none()

        ctx_data = job.render_context
        input_path = ctx_data["input_path"]
        ass_path = ctx_data["ass_path"]
        temp_dir = ctx_data["temp_dir"]

        # Get platform specs
        spec = get_platform_spec(export.platform)

        # Get video dimensions via ffprobe
        import subprocess
        probe_result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_streams", input_path,
            ],
            capture_output=True, text=True, timeout=30,
        )
        probe = json.loads(probe_result.stdout)
        video_stream = next(
            (s for s in probe.get("streams", []) if s["codec_type"] == "video"), None
        )
        if not video_stream:
            await _fail_export(db, export, job, "No video stream in input file", str(job.id))
            return

        video_width = int(video_stream["width"])
        video_height = int(video_stream["height"])

        # Compute crop
        crop_params = compute_crop_params(
            face_track=clip.face_track,
            video_width=video_width,
            video_height=video_height,
            aspect_ratio=spec["aspect_ratio"],
        )

        # Clamp duration to platform max
        clip_duration = min(clip.duration, spec["max_duration"])

        # Build FFmpeg command
        output_path = os.path.join(temp_dir, "output.mp4")
        cmd = build_ffmpeg_command(
            input_path=input_path,
            output_path=output_path,
            start_time=clip.start_time,
            duration=clip_duration,
            crop=crop_params,
            width=spec["width"],
            height=spec["height"],
            fps=spec["fps"],
            aspect_ratio=spec["aspect_ratio"],
            ass_path=ass_path,
        )

        # Run FFmpeg
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="replace")[:500]
            await _fail_export(db, export, job, f"FFmpeg failed: {error_msg}", str(job.id))
            return

        # Verify output
        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            await _fail_export(db, export, job, "FFmpeg produced no output", str(job.id))
            return

        # Sanity check: output should not be excessively large
        input_size = os.path.getsize(input_path)
        output_size = os.path.getsize(output_path)
        if output_size > input_size * 2:
            await _fail_export(
                db, export, job,
                f"Output file suspiciously large ({output_size} bytes vs {input_size} input)",
                str(job.id),
            )
            # Delete the oversized output
            os.unlink(output_path)
            return

        # Update context with output path
        job.render_context = {**ctx_data, "output_path": output_path}
        await db.commit()

        # Enqueue next step
        from arq import create_pool
        from arq.connections import RedisSettings

        pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        await pool.enqueue_job("upload_output_task", export_id)
        await pool.close()

    except Exception as e:
        try:
            export_result = await db.execute(select(Export).where(Export.id == UUID(export_id)))
            export = export_result.scalar_one_or_none()
            job_result = await db.execute(select(Job).where(Job.id == export.job_id)) if export else None
            job = job_result.scalar_one_or_none() if job_result else None
            if export and job:
                await _fail_export(db, export, job, str(e), str(job.id))
        except Exception:
            pass
        raise
    finally:
        await db.close()


async def upload_output_task(ctx, export_id: str):
    """Step 3: Upload rendered file to S3, update DB, generate download URL, cleanup."""
    db = await _get_db_session()
    job_id_str = None
    try:
        exp_uuid = UUID(export_id)

        export_result = await db.execute(select(Export).where(Export.id == exp_uuid))
        export = export_result.scalar_one_or_none()
        if not export:
            return

        job_result = await db.execute(select(Job).where(Job.id == export.job_id))
        job = job_result.scalar_one_or_none()
        if not job or not job.render_context:
            return

        job_id_str = str(job.id)
        ctx_data = job.render_context
        output_path = ctx_data.get("output_path")

        if not output_path or not os.path.exists(output_path):
            await _fail_export(db, export, job, "Rendered output file not found", job_id_str)
            return

        # Upload to S3
        s3_key = f"renders/{export.user_id}/{export.id}.mp4"
        await upload_file_to_s3(output_path, s3_key)

        # Generate presigned download URL (1 hour)
        download_url = generate_presigned_url(s3_key, expires_in=3600)

        # Update export
        export.s3_key = s3_key
        export.download_url = download_url
        export.expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        export.status = "rendered"

        # Update job
        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)

        await db.commit()

        # Cleanup temp files
        _cleanup_temp_dir(job_id_str)

    except Exception as e:
        try:
            export_result = await db.execute(select(Export).where(Export.id == UUID(export_id)))
            export = export_result.scalar_one_or_none()
            job_result = await db.execute(select(Job).where(Job.id == export.job_id)) if export else None
            job = job_result.scalar_one_or_none() if job_result else None
            if export and job:
                await _fail_export(db, export, job, str(e), str(job.id) if job else "unknown")
        except Exception:
            pass
        if job_id_str:
            _cleanup_temp_dir(job_id_str)
        raise
    finally:
        await db.close()
```

- [ ] **Step 2: Commit pipeline (tests come with export API in Task 10)**

```bash
git add backend/app/rendering/pipeline.py
git commit -m "feat(render): add three-step render pipeline tasks — prepare, execute, upload"
```

---

### Task 9: Export schemas and router

**Files:**
- Create: `backend/app/export/__init__.py`
- Create: `backend/app/export/schemas.py`
- Create: `backend/app/export/router.py`

- [ ] **Step 1: Create export schemas**

Create `backend/app/export/__init__.py` (empty file).

Create `backend/app/export/schemas.py`:

```python
"""Pydantic schemas for export API."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class ExportRequest(BaseModel):
    clip_id: UUID
    platform: Literal["shorts", "tiktok", "reels", "square", "twitter"]


class ExportResponse(BaseModel):
    id: UUID
    clip_id: UUID
    user_id: UUID
    platform: str
    aspect_ratio: str
    resolution: str
    status: str
    job_id: UUID | None
    s3_key: str | None
    download_url: str | None
    expires_at: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True


class ExportListResponse(BaseModel):
    exports: list[ExportResponse]
    total: int
```

- [ ] **Step 2: Create export router**

Create `backend/app/export/router.py`:

```python
"""Export API endpoints."""

from datetime import datetime, timezone, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.config import settings
from app.db.models import Clip, Export, Job, User, Video
from app.db.session import get_db
from app.export.schemas import ExportRequest, ExportResponse, ExportListResponse
from app.rendering.specs import get_platform_spec

router = APIRouter(prefix="/exports", tags=["exports"])


@router.post("", response_model=ExportResponse)
async def create_export(
    data: ExportRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create an export and trigger the render pipeline."""
    # Verify clip belongs to user and is selected
    clip_result = await db.execute(
        select(Clip)
        .join(Video, Clip.video_id == Video.id)
        .where(Clip.id == data.clip_id, Video.user_id == user.id)
    )
    clip = clip_result.scalar_one_or_none()
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    if clip.status != "selected":
        raise HTTPException(
            status_code=400,
            detail=f"Clip must be 'selected' to export (current: '{clip.status}')",
        )

    # Rate limit: count exports in last 24 hours
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    count_result = await db.execute(
        select(func.count(Export.id)).where(
            Export.user_id == user.id,
            Export.created_at > cutoff,
        )
    )
    export_count = count_result.scalar()
    if export_count >= settings.render_rate_limit_free:
        raise HTTPException(
            status_code=429,
            detail=f"Daily render limit reached ({settings.render_rate_limit_free}/day). Upgrade for more.",
        )

    # Get platform specs
    spec = get_platform_spec(data.platform)

    # Note: clip duration may exceed platform max — pipeline will truncate
    # to spec["max_duration"] automatically via FFmpeg -t flag. No rejection here.

    # Create job
    job = Job(
        user_id=user.id,
        video_id=clip.video_id,
        job_type="render",
        status="pending",
    )
    db.add(job)
    await db.flush()

    # Create export
    export = Export(
        clip_id=clip.id,
        user_id=user.id,
        platform=data.platform,
        aspect_ratio=spec["aspect_ratio"],
        resolution=f"{spec['width']}x{spec['height']}",
        status="pending",
        job_id=job.id,
    )
    db.add(export)
    await db.commit()
    await db.refresh(export)

    # Enqueue render pipeline
    # Note: matches existing pattern in clip_detection/router.py — commented out
    # until ARQ worker is running. Uncomment when deploying with worker:
    # from arq import create_pool
    # from arq.connections import RedisSettings
    # pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    # await pool.enqueue_job("prepare_render_task", str(export.id))
    # await pool.close()

    return export


@router.get("/{export_id}", response_model=ExportResponse)
async def get_export(
    export_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get export status and download URL (user-scoped)."""
    result = await db.execute(
        select(Export).where(Export.id == export_id, Export.user_id == user.id)
    )
    export = result.scalar_one_or_none()
    if not export:
        raise HTTPException(status_code=404, detail="Export not found")
    return export


@router.get("/clip/{clip_id}", response_model=ExportListResponse)
async def get_exports_for_clip(
    clip_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all exports for a clip (user-scoped)."""
    # Verify clip belongs to user
    clip_result = await db.execute(
        select(Clip)
        .join(Video, Clip.video_id == Video.id)
        .where(Clip.id == clip_id, Video.user_id == user.id)
    )
    if not clip_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Clip not found")

    result = await db.execute(
        select(Export)
        .where(Export.clip_id == clip_id, Export.user_id == user.id)
        .order_by(Export.created_at.desc())
    )
    exports = list(result.scalars().all())
    return ExportListResponse(exports=exports, total=len(exports))
```

- [ ] **Step 3: Commit schemas and router**

```bash
git add backend/app/export/__init__.py backend/app/export/schemas.py backend/app/export/router.py
git commit -m "feat(export): add export API — create, get, list endpoints with rate limiting"
```

---

### Task 10: Wire up worker + main app + export tests

**Files:**
- Modify: `backend/app/jobs/worker.py`
- Modify: `backend/app/main.py`
- Modify: `backend/requirements.txt`
- Create: `backend/tests/unit/test_exports.py`

- [ ] **Step 1: Update worker.py**

In `backend/app/jobs/worker.py`, add render task imports and functions:

```python
from arq.connections import RedisSettings

from app.config import settings
from app.jobs.tasks import transcribe_video, detect_clips_task
from app.rendering.pipeline import prepare_render_task, execute_render_task, upload_output_task


async def startup(ctx):
    """ARQ worker startup — initialize DB session."""
    pass


async def shutdown(ctx):
    """ARQ worker shutdown."""
    pass


class WorkerSettings:
    functions = [
        transcribe_video,
        detect_clips_task,
        prepare_render_task,
        execute_render_task,
        upload_output_task,
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 3
    job_timeout = 1800  # 30 minutes
```

- [ ] **Step 2: Update main.py**

In `backend/app/main.py`, add the export router:

```python
from app.export.router import router as exports_router
```

And add:

```python
app.include_router(exports_router)
```

- [ ] **Step 3: Add mediapipe to requirements.txt**

Append to `backend/requirements.txt`:

```
mediapipe==0.10.11
opencv-python-headless==4.9.0.80
```

Note: `opencv-python-headless` is required by mediapipe but avoids pulling in GUI dependencies.

- [ ] **Step 4: Write export API tests**

Create `backend/tests/unit/test_exports.py`:

```python
"""Tests for export API endpoints."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.db.models import Clip, Export, Job, Transcript, User, Video


@pytest.fixture
async def auth_client(client):
    """Client that is logged in."""
    await client.post("/auth/register", json={
        "email": "exportuser@example.com",
        "password": "StrongPass123!",
        "tos_accepted": True,
    })
    await client.post("/auth/login", json={
        "email": "exportuser@example.com",
        "password": "StrongPass123!",
    })
    return client


@pytest.fixture
async def selected_clip(auth_client, db_session):
    """Create a video with a selected clip ready for export."""
    me_resp = await auth_client.get("/auth/me")
    user_id = me_resp.json()["id"]

    video = Video(
        user_id=user_id,
        original_filename="test.mp4",
        s3_key=f"uploads/{user_id}/test.mp4",
        file_size=1024,
        duration=300.0,
        status="ready",
    )
    db_session.add(video)
    await db_session.flush()

    transcript = Transcript(
        video_id=video.id,
        content="hello world test",
        word_timestamps=[
            {"word": "hello", "start": 10.0, "end": 10.5},
            {"word": "world", "start": 10.5, "end": 11.0},
        ],
        language="en",
    )
    db_session.add(transcript)
    await db_session.flush()

    clip = Clip(
        video_id=video.id,
        transcript_id=transcript.id,
        start_time=10.0,
        end_time=50.0,
        duration=40.0,
        virality_score=85,
        hook="Great hook",
        status="selected",
    )
    db_session.add(clip)
    await db_session.commit()
    await db_session.refresh(clip)
    return clip


async def test_create_export(auth_client, selected_clip):
    resp = await auth_client.post("/exports", json={
        "clip_id": str(selected_clip.id),
        "platform": "shorts",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["platform"] == "shorts"
    assert data["aspect_ratio"] == "9:16"
    assert data["resolution"] == "1080x1920"
    assert data["status"] == "pending"
    assert data["job_id"] is not None


async def test_create_export_square(auth_client, selected_clip):
    resp = await auth_client.post("/exports", json={
        "clip_id": str(selected_clip.id),
        "platform": "square",
    })
    assert resp.status_code == 200
    assert resp.json()["aspect_ratio"] == "1:1"
    assert resp.json()["resolution"] == "1080x1080"


async def test_create_export_invalid_platform(auth_client, selected_clip):
    resp = await auth_client.post("/exports", json={
        "clip_id": str(selected_clip.id),
        "platform": "myspace",
    })
    assert resp.status_code == 422  # Pydantic validation


async def test_create_export_clip_not_selected(auth_client, db_session, selected_clip):
    """Can only export clips with status 'selected'."""
    # Change clip back to candidate
    await auth_client.patch(f"/clips/{selected_clip.id}", json={"status": "candidate"})

    resp = await auth_client.post("/exports", json={
        "clip_id": str(selected_clip.id),
        "platform": "shorts",
    })
    assert resp.status_code == 400
    assert "selected" in resp.json()["detail"]


async def test_create_export_clip_not_found(auth_client):
    resp = await auth_client.post("/exports", json={
        "clip_id": str(uuid4()),
        "platform": "shorts",
    })
    assert resp.status_code == 404


async def test_create_export_long_clip_allowed(auth_client, db_session):
    """Clip longer than platform max is allowed — pipeline truncates via -t flag."""
    me_resp = await auth_client.get("/auth/me")
    user_id = me_resp.json()["id"]

    video = Video(
        user_id=user_id,
        original_filename="long.mp4",
        s3_key=f"uploads/{user_id}/long.mp4",
        file_size=2048,
        duration=600.0,
        status="ready",
    )
    db_session.add(video)
    await db_session.flush()

    transcript = Transcript(
        video_id=video.id, content="test", word_timestamps=[], language="en",
    )
    db_session.add(transcript)
    await db_session.flush()

    clip = Clip(
        video_id=video.id,
        transcript_id=transcript.id,
        start_time=0.0,
        end_time=120.0,
        duration=120.0,  # 2 minutes — exceeds shorts max (60s), but pipeline truncates
        status="selected",
    )
    db_session.add(clip)
    await db_session.commit()

    resp = await auth_client.post("/exports", json={
        "clip_id": str(clip.id),
        "platform": "shorts",
    })
    assert resp.status_code == 200  # Allowed — pipeline will truncate to 60s


async def test_get_export(auth_client, selected_clip):
    # Create export first
    create_resp = await auth_client.post("/exports", json={
        "clip_id": str(selected_clip.id),
        "platform": "tiktok",
    })
    export_id = create_resp.json()["id"]

    resp = await auth_client.get(f"/exports/{export_id}")
    assert resp.status_code == 200
    assert resp.json()["platform"] == "tiktok"


async def test_get_export_not_found(auth_client):
    resp = await auth_client.get(f"/exports/{uuid4()}")
    assert resp.status_code == 404


async def test_get_exports_for_clip(auth_client, selected_clip):
    # Create two exports for same clip
    await auth_client.post("/exports", json={
        "clip_id": str(selected_clip.id),
        "platform": "shorts",
    })
    await auth_client.post("/exports", json={
        "clip_id": str(selected_clip.id),
        "platform": "reels",
    })

    resp = await auth_client.get(f"/exports/clip/{selected_clip.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2


async def test_export_scoped_to_user(client, db_session, selected_clip):
    """Another user can't see exports."""
    # Create export as first user
    await client.post("/auth/register", json={
        "email": "exportother@example.com",
        "password": "StrongPass123!",
        "tos_accepted": True,
    })
    await client.post("/auth/login", json={
        "email": "exportother@example.com",
        "password": "StrongPass123!",
    })

    resp = await client.get(f"/exports/clip/{selected_clip.id}")
    assert resp.status_code == 404


async def test_rate_limit_exports(auth_client, selected_clip, db_session):
    """Rate limit blocks after max exports per day."""
    me_resp = await auth_client.get("/auth/me")
    user_id = me_resp.json()["id"]

    # Insert 10 exports directly to hit rate limit
    for i in range(10):
        job = Job(
            user_id=user_id,
            video_id=selected_clip.video_id,
            job_type="render",
            status="completed",
        )
        db_session.add(job)
        await db_session.flush()

        exp = Export(
            clip_id=selected_clip.id,
            user_id=user_id,
            platform="shorts",
            aspect_ratio="9:16",
            resolution="1080x1920",
            status="rendered",
            job_id=job.id,
        )
        db_session.add(exp)
    await db_session.commit()

    resp = await auth_client.post("/exports", json={
        "clip_id": str(selected_clip.id),
        "platform": "shorts",
    })
    assert resp.status_code == 429
    assert "limit" in resp.json()["detail"].lower()
```

- [ ] **Step 5: Run all tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/jobs/worker.py backend/app/main.py backend/requirements.txt backend/app/export/ backend/app/rendering/pipeline.py backend/tests/unit/test_exports.py
git commit -m "feat(export): wire up export API, render pipeline tasks, and worker registration"
```

---

## Chunk 4: Frontend — Preview, Export Panel, Integration

### Task 11: Clip preview component

**Files:**
- Create: `frontend/src/components/ClipPreview/ClipPreview.tsx`

- [ ] **Step 1: Create ClipPreview component**

Create `frontend/src/components/ClipPreview/ClipPreview.tsx`:

```tsx
import { useState, useRef, useEffect } from "react";
import api from "../../api/client";

interface ClipPreviewProps {
  videoId: string;
  startTime: number;
  endTime: number;
}

export default function ClipPreview({ videoId, startTime, endTime }: ClipPreviewProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function fetchPreviewUrl() {
      try {
        const resp = await api.get(`/videos/${videoId}/preview-url`);
        setPreviewUrl(resp.data.url);
      } catch {
        setError("Could not load video preview");
      } finally {
        setLoading(false);
      }
    }
    fetchPreviewUrl();
  }, [videoId]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !previewUrl) return;

    const handleTimeUpdate = () => {
      if (video.currentTime >= endTime) {
        video.pause();
        video.currentTime = startTime;
      }
    };

    const handleLoadedMetadata = () => {
      video.currentTime = startTime;
    };

    video.addEventListener("timeupdate", handleTimeUpdate);
    video.addEventListener("loadedmetadata", handleLoadedMetadata);

    return () => {
      video.removeEventListener("timeupdate", handleTimeUpdate);
      video.removeEventListener("loadedmetadata", handleLoadedMetadata);
    };
  }, [previewUrl, startTime, endTime]);

  if (loading) return <p>Loading preview...</p>;
  if (error) return <p className="error">{error}</p>;
  if (!previewUrl) return null;

  return (
    <div className="clip-preview">
      <h4>Preview</h4>
      <video
        ref={videoRef}
        src={`${previewUrl}#t=${startTime},${endTime}`}
        controls
        style={{ width: "100%", maxHeight: 400, borderRadius: 8 }}
      />
      <p className="clip-preview__info">
        {startTime.toFixed(1)}s — {endTime.toFixed(1)}s ({(endTime - startTime).toFixed(1)}s)
      </p>
    </div>
  );
}
```

- [ ] **Step 2: Add preview URL endpoint to videos router**

This endpoint generates a short-lived presigned URL for in-browser preview. Add to `backend/app/videos/router.py`:

```python
@router.get("/{video_id}/preview-url")
async def get_preview_url(
    video_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a short-lived presigned URL for in-browser video preview."""
    result = await db.execute(
        select(Video).where(Video.id == video_id, Video.user_id == user.id)
    )
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    from app.videos.storage import generate_presigned_url
    url = generate_presigned_url(video.s3_key, expires_in=900)  # 15 minutes
    return {"url": url}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ClipPreview/ClipPreview.tsx backend/app/videos/router.py
git commit -m "feat(frontend): add in-browser clip preview with presigned URL"
```

---

### Task 12: Export panel component

**Files:**
- Create: `frontend/src/components/ExportPanel/ExportPanel.tsx`

- [ ] **Step 1: Create ExportPanel component**

Create `frontend/src/components/ExportPanel/ExportPanel.tsx`:

```tsx
import { useState, useEffect } from "react";
import api from "../../api/client";
import JobProgress from "../VideoUpload/JobProgress";

interface ExportPanelProps {
  clipId: string;
  clipStatus: string;
  onExportComplete: () => void;
}

interface ExportRecord {
  id: string;
  platform: string;
  aspect_ratio: string;
  resolution: string;
  status: string;
  job_id: string | null;
  download_url: string | null;
}

const PLATFORMS = [
  { key: "shorts", label: "YouTube Shorts", ratio: "9:16" },
  { key: "tiktok", label: "TikTok", ratio: "9:16" },
  { key: "reels", label: "Instagram Reels", ratio: "9:16" },
  { key: "square", label: "Instagram Square", ratio: "1:1" },
  { key: "twitter", label: "X (Twitter)", ratio: "16:9" },
];

export default function ExportPanel({ clipId, clipStatus, onExportComplete }: ExportPanelProps) {
  const [selectedPlatform, setSelectedPlatform] = useState("shorts");
  const [exporting, setExporting] = useState(false);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [exports, setExports] = useState<ExportRecord[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    fetchExports();
  }, [clipId]);

  async function fetchExports() {
    try {
      const resp = await api.get(`/exports/clip/${clipId}`);
      setExports(resp.data.exports);
    } catch {
      // No exports yet
    }
  }

  async function handleExport() {
    setExporting(true);
    setError("");
    try {
      const resp = await api.post("/exports", {
        clip_id: clipId,
        platform: selectedPlatform,
      });
      if (resp.data.job_id) {
        setActiveJobId(resp.data.job_id);
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || "Export failed");
    } finally {
      setExporting(false);
    }
  }

  function handleJobComplete() {
    setActiveJobId(null);
    fetchExports();
    onExportComplete();
  }

  if (clipStatus !== "selected") return null;

  return (
    <div className="export-panel">
      <h4>Export Clip</h4>

      <div className="export-panel__platforms">
        {PLATFORMS.map((p) => (
          <button
            key={p.key}
            className={`export-panel__platform-btn ${selectedPlatform === p.key ? "export-panel__platform-btn--active" : ""}`}
            onClick={() => setSelectedPlatform(p.key)}
          >
            <span className="export-panel__platform-label">{p.label}</span>
            <span className="export-panel__platform-ratio">{p.ratio}</span>
          </button>
        ))}
      </div>

      <button
        onClick={handleExport}
        disabled={exporting || !!activeJobId}
        className="export-btn"
      >
        {exporting ? "Starting..." : activeJobId ? "Rendering..." : "Export"}
      </button>

      {error && <p className="error">{error}</p>}

      {activeJobId && (
        <JobProgress jobId={activeJobId} onComplete={handleJobComplete} />
      )}

      {exports.length > 0 && (
        <div className="export-panel__history">
          <h5>Export History</h5>
          {exports.map((exp) => (
            <div key={exp.id} className="export-panel__item">
              <span>{PLATFORMS.find((p) => p.key === exp.platform)?.label || exp.platform}</span>
              <span className="export-panel__item-status">{exp.status}</span>
              {exp.download_url && exp.status === "rendered" && (
                <a href={exp.download_url} download className="download-btn">
                  Download
                </a>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/ExportPanel/ExportPanel.tsx
git commit -m "feat(frontend): add ExportPanel with platform selector and download links"
```

---

### Task 13: VideoPage integration + styles

**Files:**
- Modify: `frontend/src/pages/VideoPage.tsx`
- Modify: `frontend/src/App.css`

- [ ] **Step 1: Update VideoPage to include ExportPanel and ClipPreview**

Replace `frontend/src/pages/VideoPage.tsx` with:

```tsx
import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import api from "../api/client";
import ClipList from "../components/ClipCandidates/ClipList";
import ClipAdjuster from "../components/ClipCandidates/ClipAdjuster";
import ClipPreview from "../components/ClipPreview/ClipPreview";
import ExportPanel from "../components/ExportPanel/ExportPanel";
import JobProgress from "../components/VideoUpload/JobProgress";

interface Video {
  id: string;
  original_filename: string;
  status: string;
  duration: number | null;
}

export default function VideoPage() {
  const { videoId } = useParams<{ videoId: string }>();
  const navigate = useNavigate();
  const [video, setVideo] = useState<Video | null>(null);
  const [selectedClip, setSelectedClip] = useState<any>(null);
  const [detectJobId, setDetectJobId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    async function fetchVideo() {
      try {
        const resp = await api.get(`/videos/${videoId}`);
        setVideo(resp.data);
      } catch {
        navigate("/");
      } finally {
        setLoading(false);
      }
    }
    fetchVideo();
  }, [videoId, navigate]);

  async function handleDetectClips() {
    if (!videoId) return;
    try {
      const resp = await api.post(`/clips/detect/${videoId}`);
      if (resp.data.job_id) {
        setDetectJobId(resp.data.job_id);
      }
    } catch (err: any) {
      alert(err.response?.data?.detail || "Failed to start clip detection");
    }
  }

  if (loading) return <p>Loading...</p>;
  if (!video) return <p>Video not found.</p>;

  return (
    <div className="video-page">
      <button onClick={() => navigate("/")} className="back-btn">
        Back to Dashboard
      </button>

      <h2>{video.original_filename}</h2>
      <p>
        Status: <strong>{video.status}</strong>
        {video.duration && <> | Duration: {Math.round(video.duration)}s</>}
      </p>

      {video.status === "ready" && !detectJobId && (
        <button onClick={handleDetectClips} className="detect-btn">
          Detect Viral Clips
        </button>
      )}

      {detectJobId && (
        <JobProgress
          jobId={detectJobId}
          onComplete={() => {
            setDetectJobId(null);
            setRefreshKey((k) => k + 1);
          }}
        />
      )}

      {selectedClip && videoId && (
        <ClipPreview
          videoId={videoId}
          startTime={selectedClip.start_time}
          endTime={selectedClip.end_time}
        />
      )}

      {selectedClip && video.duration && (
        <ClipAdjuster
          clip={selectedClip}
          videoDuration={video.duration}
          onUpdate={() => setRefreshKey((k) => k + 1)}
        />
      )}

      {selectedClip && selectedClip.status === "selected" && (
        <ExportPanel
          clipId={selectedClip.id}
          clipStatus={selectedClip.status}
          onExportComplete={() => setRefreshKey((k) => k + 1)}
        />
      )}

      {videoId && (
        <ClipList
          key={refreshKey}
          videoId={videoId}
          onClipSelect={setSelectedClip}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 2: Add export panel and preview styles to App.css**

Append to `frontend/src/App.css`:

```css
/* Clip Preview */
.clip-preview {
  margin: 16px 0;
  padding: 16px;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  border-radius: 8px;
}

.clip-preview h4 {
  margin: 0 0 12px;
}

.clip-preview__info {
  margin-top: 8px;
  font-size: 13px;
  color: #6b7280;
}

/* Export Panel */
.export-panel {
  padding: 16px;
  margin: 16px 0;
  background: #fff7ed;
  border: 1px solid #fed7aa;
  border-radius: 8px;
}

.export-panel h4 {
  margin: 0 0 12px;
}

.export-panel__platforms {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.export-panel__platform-btn {
  padding: 8px 12px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  background: white;
  cursor: pointer;
  text-align: center;
  transition: border-color 0.2s;
}

.export-panel__platform-btn:hover {
  border-color: #f97316;
}

.export-panel__platform-btn--active {
  border-color: #f97316;
  background: #fff7ed;
  box-shadow: 0 0 0 2px rgba(249, 115, 22, 0.2);
}

.export-panel__platform-label {
  display: block;
  font-size: 13px;
  font-weight: 600;
}

.export-panel__platform-ratio {
  display: block;
  font-size: 11px;
  color: #9ca3af;
}

.export-btn {
  padding: 10px 20px;
  background: #f97316;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
}

.export-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.export-panel__history {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid #fed7aa;
}

.export-panel__history h5 {
  margin: 0 0 8px;
  font-size: 13px;
}

.export-panel__item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 6px 0;
  font-size: 13px;
}

.export-panel__item-status {
  color: #6b7280;
  font-size: 12px;
}

.download-btn {
  padding: 4px 10px;
  background: #059669;
  color: white;
  border: none;
  border-radius: 4px;
  font-size: 12px;
  text-decoration: none;
  cursor: pointer;
}

.download-btn:hover {
  background: #047857;
}
```

- [ ] **Step 3: Verify frontend builds**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: Clean build, no errors

- [ ] **Step 4: Run all backend tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/VideoPage.tsx frontend/src/App.css frontend/src/components/ClipPreview/ frontend/src/components/ExportPanel/
git commit -m "feat(frontend): integrate export panel, clip preview, and render workflow into VideoPage"
```

---

## Post-Implementation

After all tasks are complete:

1. Update `docs/build_log.md` with Week 3 summary
2. Run full test suite: `cd backend && python -m pytest tests/ -v`
3. Verify frontend builds: `cd frontend && npm run build`
4. Merge develop to main: `git checkout main && git merge develop --no-ff -m "feat: Week 3 — render pipeline, captions, export"`
5. Tag: `git tag -a v0.3.0 -m "feat: render pipeline, captions, export in all three formats"`
6. Switch back: `git checkout develop`
