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
