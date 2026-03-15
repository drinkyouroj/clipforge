# ClipForge Build Log

## 2026-03-13 — Session 1: Project Scaffold + Week 1 Plan
- Initialized git repo on `develop` branch
- Created project scaffold
- Week 1 plan written to `docs/superpowers/plans/` and `build_plan.md`

## 2026-03-13 — Session 2: Week 1 Implementation

### Infrastructure (Tasks 1-3)
- Docker Compose: PostgreSQL 16 + Redis 7
- `.env.example` with all config vars

### Database Schema (Tasks 4-5)
- DECISION_001: 6-table schema (users, videos, transcripts, clips, jobs, exports)
- UUID v4 PKs, CHECK constraints on status fields, JSONB for word_timestamps
- SQLAlchemy 2.0 async models + Alembic migration
- 6 model tests passing

### Auth System (Tasks 6-7)
- DECISION_002: JWT in httpOnly cookies
- Registration with ToS acceptance, login, logout, /auth/me
- Email verification + password reset (stubbed)
- passlib[bcrypt] with bcrypt pinned to 4.0.1
- 8 auth tests passing

### Video Upload Pipeline (Tasks 8-10)
- DECISION_003: R2 storage, user-scoped paths, signed URLs
- File validation: magic bytes (filetype lib), ffprobe (video+audio, max 3hr)
- S3 storage: upload, download, presigned URLs, delete
- Upload service: rate limiting (5/hr), temp file cleanup, S3 cleanup on DB failure
- REST endpoints: POST /videos/upload, GET /videos/, GET /videos/{id}, DELETE /videos/{id}
- 12 validation/storage/upload tests passing

### Job Queue (Task 11)
- ARQ worker scaffold with transcribe task stub
- Job status endpoints: GET /jobs/{id}, GET /jobs/video/{video_id}
- User-scoped job access
- 5 job tests passing

### Transcription (Tasks 12-13)
- DECISION_004: Audio extraction (mono 64kbps MP3), Whisper API chunking (24MB limit)
- Audio extraction via FFmpeg, chunking for long videos
- Whisper API integration with word-level timestamps
- Transcript storage and retrieval endpoint
- Full transcribe_video ARQ task (download → extract → transcribe → store)
- 6 transcription tests passing

### Frontend (Tasks 14-16)
- React + Vite + TypeScript scaffold
- API client with httpOnly cookie credentials
- Login/Register pages with form validation
- Dashboard: upload form with progress bar, job status polling, video list
- Frontend builds clean (TypeScript strict mode)

### Stats
- **37 tests passing** across 7 test files
- **4 DECISION docs** filed
- **13 commits** on develop branch
- **Backend:** 6 modules (auth, videos, transcription, jobs, db, config)
- **Frontend:** auth pages, dashboard, upload flow

### Known Issues / Fixes Applied
- PostgreSQL 15→16 (volume incompatibility)
- Docker port conflicts with ghosteditor containers
- `server_default="gen_random_uuid()"` → `server_default=sa.text('gen_random_uuid()')`
- pytest-asyncio loop scope: `session` → `function` (fixed event loop mismatch)
- bcrypt 5.0 incompatible with passlib → pinned to 4.0.1
- python-magic → filetype (pure Python, no native libmagic dependency)
- openai package needed separate install for Python 3.12

## 2026-03-13 — Session 3: Week 2 Implementation (Clip Detection + Virality Scoring)

### DECISION_005: Clip Detection Prompt Design
- Versioned prompt files in `backend/app/clip_detection/prompts/`
- Claude API (`claude-sonnet-4-5`) for transcript analysis
- JSON resilience: strip markdown fences, trailing commas, 2 retries
- Timestamp validation: clamp to video duration, 15-90s clip bounds
- Deduplication: remove clips with >50% time overlap, keep higher score
- Long video handling: split transcript at midpoint with 5-min overlap for >60min

### DECISION_006: Clip Selection Data Model
- Status transitions via API: only `candidate↔selected` allowed
- Other transitions (`rendering`, `rendered`, `failed`) reserved for render pipeline
- No separate selection table — status field on Clip model is sufficient
- Original boundary values lost on adjustment (accepted tradeoff, re-detection is recovery path)

### Clip Detection Backend
- `detector.py`: Claude API integration, transcript formatting, long video splitting
- `scorer.py`: JSON cleaning, clip validation, deduplication
- `router.py`: GET /clips/video/{id}, GET /clips/{id}, PATCH /clips/{id}, POST /clips/detect/{id}
- `schemas.py`: ClipResponse, ClipListResponse, ClipUpdateRequest
- `prompts/virality_v1.txt`: Full scoring rubric with injection guards
- `detect_clips_task` in jobs/tasks.py: ARQ task with job status management

### Clip Detection Frontend
- `ClipCard.tsx`: Score bar with color gradient, hook display, platform tags
- `ClipList.tsx`: Fetches and displays clip candidates sorted by virality score
- `ClipAdjuster.tsx`: Range sliders for start/end time, visual timeline, save boundaries
- `VideoPage.tsx`: Detect button, job progress, clip selection and adjustment

### Stats
- **60 tests passing** across 9 test files (+23 from Week 1)
- **6 DECISION docs** filed (DECISION_001 through DECISION_006)
- **5 commits** on develop for Week 2
- **Backend:** clip_detection module (detector, scorer, router, schemas, prompts)
- **Frontend:** ClipCandidates components, VideoPage with full clip workflow

## 2026-03-13 — Session 4: Week 3 Implementation (Render Pipeline + Captions + Export)

### DECISION_007: Render Pipeline and FFmpeg Command Design
- Three-step chained ARQ pipeline: prepare_render → execute_render → upload_output
- Export-centric model: one Export per clip-platform, Export.status tracks lifecycle
- Face detection via mediapipe with center crop fallback
- ASS/SSA captions with per-word yellow/white highlighting
- FFmpeg: -ss input seeking, crop/scale/ass filter chain, H.264 CRF 23, AAC 192k, loudnorm -14 LUFS
- Output size sanity check (< 2x input), temp file cleanup with 2-level subdirectory sweep

### Database Changes
- `Clip.face_track` (JSONB) — cached mediapipe face position track, reusable across exports
- `Export.status` (String, CHECK) — pending → rendering → rendered → failed
- `Export.job_id` (UUID FK) — links export to its render job
- `Job.render_context` (JSONB) — pipeline state shared between steps
- Alembic migration generated and committed

### Rendering Modules
- `specs.py`: Platform spec lookup for 5 platforms (shorts, tiktok, reels, square, twitter)
- `captions.py`: Word timestamps → ASS subtitle file with per-word color highlighting
- `reframe.py`: Face detection, moving average smoothing (window=15), crop calculation per aspect ratio
- `ffmpeg_cmd.py`: FFmpeg command assembly with crop/scale/ass/loudnorm filter chain
- `pipeline.py`: Three chained ARQ tasks with error handling and temp file cleanup

### Export API
- `POST /exports` — create export + job, validate clip ownership and selection, rate limit (10/day)
- `GET /exports/{id}` — user-scoped export status and download URL
- `GET /exports/clip/{clip_id}` — list all exports for a clip
- Pydantic schemas: ExportRequest, ExportResponse, ExportListResponse

### Frontend
- `ClipPreview.tsx`: In-browser video preview using presigned URL + media fragments
- `ExportPanel.tsx`: Platform selector (5 options), export trigger, job progress polling, download links
- `VideoPage.tsx`: Integrated preview, adjuster, and export panel for selected clips
- `GET /videos/{id}/preview-url` — 15-minute presigned URL for in-browser preview

### Stats
- **104 tests passing** across 13 test files (+44 from Week 2)
- **7 DECISION docs** filed (DECISION_001 through DECISION_007)
- **13 commits** on develop for Week 3
- **Backend:** rendering module (specs, captions, reframe, ffmpeg_cmd, pipeline), export module (router, schemas)
- **Frontend:** ClipPreview, ExportPanel, updated VideoPage with full export workflow

## 2026-03-13 — Session 5: Week 4 Implementation (Billing + Polish + Launch)

### DECISION_008: Billing Model
- 3-tier credit-based subscriptions: free (10/mo), starter ($19/mo, 100), pro ($49/mo, unlimited)
- Billing state on User model (5 new columns), no separate tables
- Atomic credit enforcement via UPDATE...WHERE...RETURNING
- Stripe Checkout for subscription creation, Billing Portal for management
- Out-of-order webhook protection via event timestamps

### DECISION_009: Video Lifecycle & Cleanup
- Enhanced user-initiated delete: immediate S3 cleanup, soft-delete DB records
- DB records retained 7 days for undo
- Daily ARQ cron task: auto-expire (30d), hard-delete (7d after soft-delete), billing reset
- Per-video transactions, skip auto-expire for videos with running jobs

### Database Changes
- `User.stripe_customer_id` (String, unique) — Stripe customer reference
- `User.subscription_tier` (String, CHECK: free/starter/pro, default: free)
- `User.subscription_stripe_id` (String) — Stripe subscription ID
- `User.current_period_end` (DateTime) — billing cycle end
- `User.period_exports_used` (Integer, default: 0) — reset on invoice.paid
- Alembic migration generated and committed

### Billing Backend
- `billing/service.py`: Stripe checkout, portal, webhook handlers, credit checks
- `billing/router.py`: POST /checkout, POST /portal, GET /status, POST /webhook
- `billing/schemas.py`: CheckoutRequest, PortalResponse, BillingStatusResponse
- Credit enforcement replaces 24-hour rate limit in export endpoint
- Free-tier reset via daily cron + current_period_end at registration

### Video Lifecycle
- Enhanced `soft_delete_video`: immediate S3 cleanup, export S3 cleanup, job cancellation
- `cleanup_expired_content` ARQ cron task: auto-expire, hard-delete, billing reset
- Per-video transactions, dependency-order deletes (exports → clips → transcript → jobs → video)

### Export API Enhancement
- `GET /exports` — paginated user export history for account page

### Frontend
- `LandingPage.tsx`: Hero, how it works, features, pricing, footer
- `AccountPage.tsx`: Profile, subscription management, export history
- `TermsPage.tsx`: Placeholder Terms of Service
- `PrivacyPage.tsx`: Placeholder Privacy Policy
- `App.tsx`: New page routes (landing, account, terms, privacy)
- `DashboardPage.tsx`: Account link in header

### Stats
- **125 tests passing** across 20 test files (+21 from Week 3)
- **9 DECISION docs** filed (DECISION_001 through DECISION_009)
- **18 commits** on develop for Week 4
- **Backend:** billing module (service, router, schemas), enhanced delete, cleanup task
- **Frontend:** LandingPage, AccountPage, TermsPage, PrivacyPage, routing updates

## 2026-03-15 — CLI/TUI Implementation

### DECISION_010: CLI/TUI Pipeline Design
- Standalone CLI tool, no server/DB/S3 dependencies
- Local Whisper via faster-whisper, local LLM via OpenAI-compatible API
- Rich terminal output with progress bars and colored tables

### CLI Features
- `clipforge process <video>` with 12 flags
- `clipforge setup` for interactive configuration
- Config resolution: CLI flags > env vars > config file > interactive prompt
- Interactive clip selection or auto via --min-score/--all
- --detect-only mode for preview without rendering
- Multi-platform rendering with face track caching
- Idempotent output (skip existing, --overwrite to force)
- Secure temp directory, empty transcript guard

### Stats
- **3 new test files** (config, transcribe, render) — 11 tests
- **2 new source files** (cli.py, cli_config.py)
- **1 new packaging file** (pyproject.toml)
- **4 new dependencies** (typer, faster-whisper, tomli, tomli-w)
