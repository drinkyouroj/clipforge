# Week 1: Foundation + Upload Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the full ClipForge backend scaffold (auth, upload, transcription) with a basic React frontend that lets a user register, upload a video, and see it transcribed via Whisper.

**Architecture:** FastAPI backend with PostgreSQL (via SQLAlchemy async + Alembic migrations), ARQ job queue backed by Redis, S3-compatible storage (Cloudflare R2) for video files. React + Vite frontend. The Adversarial Agent Protocol governs all significant design decisions — DECISION docs must be written and committed before any related code.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0 (async), Alembic, ARQ, PostgreSQL 15, Redis 7, `python-jose[cryptography]`, `passlib[bcrypt]`, `python-multipart`, `python-magic`, `ffmpeg-python`, OpenAI Whisper API, React 18, Vite 5, TypeScript

---

## File Structure

```
clipforge/
├── CLAUDE.md
├── .gitignore
├── .env.example
├── docs/
│   ├── blueprint.md                        # Product spec reference
│   ├── build_log.md                        # Running session log
│   ├── decisions/
│   │   ├── DECISION_001_database_schema.md
│   │   ├── DECISION_002_auth_flow.md
│   │   ├── DECISION_003_file_storage.md
│   │   └── DECISION_004_transcription_pipeline.md
│   └── superpowers/plans/                  # This plan lives here
├── infra/
│   └── docker-compose.yml                  # PostgreSQL + Redis
├── backend/
│   ├── requirements.txt
│   ├── alembic.ini
│   ├── app/
│   │   ├── db/
│   │   │   ├── migrations/
│   │   │   │   ├── env.py
│   │   │   │   └── versions/               # Migration files
│   │   ├── __init__.py
│   │   ├── main.py                         # FastAPI app entry
│   │   ├── config.py                       # Settings from env vars
│   │   ├── db/
│   │   │   ├── __init__.py
│   │   │   ├── session.py                  # Async engine + session
│   │   │   └── models.py                   # All SQLAlchemy models
│   │   ├── auth/
│   │   │   ├── __init__.py
│   │   │   ├── router.py                   # Auth endpoints
│   │   │   ├── service.py                  # Auth business logic
│   │   │   ├── dependencies.py             # get_current_user dep
│   │   │   └── schemas.py                  # Pydantic models
│   │   ├── videos/
│   │   │   ├── __init__.py
│   │   │   ├── router.py                   # Upload + list endpoints
│   │   │   ├── service.py                  # Upload logic, S3 ops
│   │   │   ├── validation.py               # Magic bytes, ffprobe checks
│   │   │   ├── storage.py                  # S3/R2 client wrapper
│   │   │   └── schemas.py                  # Pydantic models
│   │   ├── transcription/
│   │   │   ├── __init__.py
│   │   │   ├── router.py                   # Transcription status endpoint
│   │   │   ├── service.py                  # Whisper API integration
│   │   │   ├── audio.py                    # FFmpeg audio extraction
│   │   │   └── schemas.py                  # Pydantic models
│   │   └── jobs/
│   │       ├── __init__.py
│   │       ├── worker.py                   # ARQ worker definition
│   │       ├── tasks.py                    # Job functions (transcribe, etc.)
│   │       ├── router.py                   # Job status endpoint
│   │       └── schemas.py                  # Pydantic models
│   └── tests/
│       ├── conftest.py                     # Shared fixtures
│       ├── fixtures/                       # Sample video clips for testing
│       └── unit/
│           ├── test_auth.py
│           ├── test_upload.py
│           ├── test_validation.py
│           ├── test_models.py
│           ├── test_transcription.py
│           └── test_jobs.py
├── frontend/
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── api/
│       │   └── client.ts                   # Axios instance with auth
│       ├── components/
│       │   ├── Auth/
│       │   │   ├── LoginForm.tsx
│       │   │   └── RegisterForm.tsx
│       │   └── VideoUpload/
│       │       ├── UploadDropzone.tsx
│       │       └── JobProgress.tsx
│       └── pages/
│           ├── LoginPage.tsx
│           ├── RegisterPage.tsx
│           └── DashboardPage.tsx
```

---

## Chunk 1: Project Scaffold + Infrastructure + DECISION_001

### Task 1: Git Init and Project Scaffold

**Files:**
- Create: `.gitignore`
- Create: `.env.example`
- Create: `docs/build_log.md`
- Create: `docs/blueprint.md`

- [ ] **Step 1: Initialize git repo on develop branch**

```bash
cd /Users/justin/CascadeProjects/clipforge
git init
git checkout -b develop
```

- [ ] **Step 2: Create .gitignore**

```gitignore
node_modules/
.env
*.pyc
__pycache__/
uploads/
outputs/
rendered/
.DS_Store
*.mov
*.mp4
*.avi
*.mkv
*.webm
dist/
.vite/
*.egg-info/
.pytest_cache/
htmlcov/
venv/
```

- [ ] **Step 3: Create .env.example**

```env
# Database
DATABASE_URL=postgresql+asyncpg://clipforge:clipforge@localhost:5432/clipforge

# Redis
REDIS_URL=redis://localhost:6379

# Auth
JWT_SECRET_KEY=change-me-in-production
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=60

# S3/R2 Storage
S3_ENDPOINT_URL=https://your-account.r2.cloudflarestorage.com
S3_ACCESS_KEY_ID=your-access-key
S3_SECRET_ACCESS_KEY=your-secret-key
S3_BUCKET_NAME=clipforge-uploads
S3_REGION=auto

# OpenAI (Whisper)
OPENAI_API_KEY=your-openai-key

# Anthropic (Clip Detection)
ANTHROPIC_API_KEY=your-anthropic-key
```

- [ ] **Step 4: Create docs/build_log.md**

```markdown
# ClipForge Build Log

## 2026-03-13 — Session 1: Project Scaffold + Week 1 Plan
- Initialized git repo on `develop` branch
- Created project scaffold
- Week 1 plan written to `docs/superpowers/plans/`
```

- [ ] **Step 5: Create docs/blueprint.md**

```markdown
# ClipForge Blueprint

See CLAUDE.md for the full product spec, tech stack decisions, and build order.
This file exists as a placeholder per the project structure spec.
The authoritative spec lives in CLAUDE.md.
```

- [ ] **Step 6: Initial commit**

```bash
git add .gitignore .env.example CLAUDE.md docs/
git commit -m "chore: initial project scaffold with CLAUDE.md and blueprint"
git tag -a v0.0.1 -m "chore: project initialization"
```

---

### Task 2: Docker Compose — PostgreSQL + Redis

**Files:**
- Create: `infra/docker-compose.yml`

- [ ] **Step 1: Create docker-compose.yml**

```yaml
version: "3.9"

services:
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_USER: clipforge
      POSTGRES_PASSWORD: clipforge
      POSTGRES_DB: clipforge
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redisdata:/data

volumes:
  pgdata:
  redisdata:
```

- [ ] **Step 2: Start services and verify**

```bash
cd infra && docker compose up -d
docker compose ps  # Both should be "running"
```

- [ ] **Step 3: Commit**

```bash
git add infra/docker-compose.yml
git commit -m "chore(infra): add docker-compose with PostgreSQL 15 and Redis 7"
```

---

### Task 3: DECISION_001 — Database Schema

**Files:**
- Create: `docs/decisions/DECISION_001_database_schema.md`

- [ ] **Step 1: Write DECISION_001 using the Adversarial Agent Protocol**

Run the three-agent debate (ARCHITECT / ADVERSARY / JUDGE) to decide the database schema. The schema must cover:

- `users` table: id, email, hashed_password, created_at, tos_accepted_at, is_active, email_verified
- `videos` table: id, user_id (FK), filename, original_filename, s3_key, file_size, duration, mime_type, status (enum: uploaded/processing/ready/failed/deleted), uploaded_at, deleted_at (soft delete)
- `transcripts` table: id, video_id (FK), content (TEXT), word_timestamps (JSONB), whisper_model, language, created_at
- `clips` table: id, video_id (FK), transcript_id (FK), start_time, end_time, duration, virality_score, hook, reasoning, clip_type, suggested_title, platform_fit (JSONB), status (enum: candidate/selected/rendering/rendered/failed), rendered_s3_key, created_at
- `jobs` table: id, user_id (FK), video_id (FK), job_type (enum: transcribe/detect_clips/render), status (enum: pending/running/completed/failed), error_message, started_at, completed_at, created_at
- `exports` table: id, clip_id (FK), user_id (FK), platform, aspect_ratio, resolution, s3_key, download_url, expires_at, created_at

Key decisions for the protocol to resolve:
- UUID vs serial for PKs
- Whether to store transcripts encrypted or delete after clip detection
- Index strategy for user-scoped queries
- JSONB vs normalized tables for word_timestamps and platform_fit

Write the full ARCHITECT/ADVERSARY/JUDGE debate in the decision doc.

- [ ] **Step 2: Commit the decision doc BEFORE writing any code**

```bash
git add docs/decisions/DECISION_001_database_schema.md
git commit -m "docs(decisions): add DECISION_001 database schema"
```

---

### Task 4: Backend Scaffold + Database Models + Migration

**Files:**
- Create: `backend/requirements.txt`
- Create: `backend/app/__init__.py`
- Create: `backend/app/config.py`
- Create: `backend/app/main.py`
- Create: `backend/app/db/__init__.py`
- Create: `backend/app/db/session.py`
- Create: `backend/app/db/models.py`
- Create: `backend/alembic.ini`
- Create: `backend/app/db/migrations/env.py`
- Create: `backend/tests/unit/test_models.py`

- [ ] **Step 1: Create requirements.txt**

```
fastapi==0.109.2
uvicorn[standard]==0.27.1
sqlalchemy[asyncio]==2.0.27
asyncpg==0.29.0
alembic==1.13.1
pydantic==2.6.1
pydantic-settings==2.1.0
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
python-multipart==0.0.9
python-magic==0.4.27
ffmpeg-python==0.2.0
httpx==0.27.0
arq==0.25.0
boto3==1.34.49
openai==1.12.0
anthropic==0.18.1
pytest==8.0.1
pytest-asyncio==0.23.5
```

- [ ] **Step 2: Set up venv and install**

```bash
cd /Users/justin/CascadeProjects/clipforge/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

- [ ] **Step 3: Create app/config.py**

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://clipforge:clipforge@localhost:5432/clipforge"
    redis_url: str = "redis://localhost:6379"
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    s3_endpoint_url: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_bucket_name: str = "clipforge-uploads"
    s3_region: str = "auto"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    max_upload_size: int = 500 * 1024 * 1024  # 500MB
    upload_rate_limit: int = 5  # per hour
    render_rate_limit_free: int = 10  # per day

    class Config:
        env_file = ".env"


settings = Settings()
```

- [ ] **Step 4: Create app/db/session.py**

```python
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from app.config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncSession:
    async with async_session() as session:
        yield session
```

- [ ] **Step 5: Create app/db/models.py implementing DECISION_001 schema**

All models with proper relationships, enums, indexes, and user-scoped query patterns as determined by DECISION_001. Must include:
- `User`, `Video`, `Transcript`, `Clip`, `Job`, `Export` models
- SQLAlchemy enums for status fields
- Indexes on `(user_id, created_at)` for all user-scoped tables
- `deleted_at` soft-delete on `Video`

- [ ] **Step 6: Create app/main.py (minimal)**

```python
from fastapi import FastAPI

app = FastAPI(title="ClipForge", version="0.1.0")


@app.get("/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 7: Write test_models.py — verify model definitions**

```python
import pytest
from app.db.models import User, Video, Transcript, Clip, Job, Export

def test_user_model_has_required_fields():
    """Verify User model has all fields from DECISION_001."""
    assert hasattr(User, "id")
    assert hasattr(User, "email")
    assert hasattr(User, "hashed_password")
    assert hasattr(User, "tos_accepted_at")
    assert hasattr(User, "email_verified")
    assert hasattr(User, "is_active")

def test_video_model_has_soft_delete():
    assert hasattr(Video, "deleted_at")
    assert hasattr(Video, "user_id")

def test_transcript_model_has_word_timestamps():
    assert hasattr(Transcript, "word_timestamps")
    assert hasattr(Transcript, "video_id")
```

- [ ] **Step 8: Run test_models.py to verify it fails**

```bash
pytest tests/unit/test_models.py -v
```

- [ ] **Step 9: Set up Alembic with migrations under app/db/migrations/**

```bash
cd /Users/justin/CascadeProjects/clipforge/backend
alembic init app/db/migrations
```

Edit `app/db/migrations/env.py` to use async engine and import models.
Edit `alembic.ini` to set `script_location = app/db/migrations` and `sqlalchemy.url`.

- [ ] **Step 10: Generate and run initial migration**

```bash
alembic revision --autogenerate -m "initial schema from DECISION_001"
alembic upgrade head
```

- [ ] **Step 11: Run test_models.py — should pass**

```bash
pytest tests/unit/test_models.py -v
```

- [ ] **Step 12: Verify tables exist**

```bash
docker exec -it infra-postgres-1 psql -U clipforge -c "\dt"
```

- [ ] **Step 13: Commit**

```bash
git add backend/
git commit -m "feat(db): initial schema and backend scaffold from DECISION_001"
```

---

## Chunk 2: Auth System

### Task 5: DECISION_002 — Auth Flow

**Files:**
- Create: `docs/decisions/DECISION_002_auth_flow.md`

- [ ] **Step 1: Write DECISION_002 using the Adversarial Agent Protocol**

Per CLAUDE.md, the protocol is required for "Any auth or payment flow." Key decisions:
- JWT delivery: httpOnly cookie (required by security non-negotiables) — cookie settings (SameSite, Secure, path, expiry)
- Registration: require ToS acceptance checkbox, store `tos_accepted_at` timestamp
- Email verification: flow design (send verification link on register, verify endpoint)
- Password reset: flow design (request reset → email link → reset endpoint)
- Password requirements: minimum complexity rules
- Rate limiting on auth endpoints (brute-force prevention)
- Account lockout policy after N failed login attempts

- [ ] **Step 2: Commit the decision doc BEFORE writing any code**

```bash
git add docs/decisions/DECISION_002_auth_flow.md
git commit -m "docs(decisions): add DECISION_002 auth flow"
```

---

### Task 6: Auth — Registration + Login + JWT (httpOnly cookies)

**Files:**
- Create: `backend/app/auth/__init__.py`
- Create: `backend/app/auth/schemas.py`
- Create: `backend/app/auth/service.py`
- Create: `backend/app/auth/dependencies.py`
- Create: `backend/app/auth/router.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/unit/test_auth.py`

- [ ] **Step 1: Write test_auth.py — registration, login, ToS, cookies**

```python
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_user(client):
    resp = await client.post("/auth/register", json={
        "email": "test@example.com",
        "password": "StrongPass123!",
        "tos_accepted": True,
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "test@example.com"
    assert "id" in data


@pytest.mark.asyncio
async def test_register_requires_tos(client):
    resp = await client.post("/auth/register", json={
        "email": "notos@example.com",
        "password": "StrongPass123!",
        "tos_accepted": False,
    })
    assert resp.status_code == 422  # ToS acceptance required


@pytest.mark.asyncio
async def test_register_duplicate_email(client):
    payload = {"email": "dupe@example.com", "password": "StrongPass123!", "tos_accepted": True}
    await client.post("/auth/register", json=payload)
    resp = await client.post("/auth/register", json=payload)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_login_sets_httponly_cookie(client):
    await client.post("/auth/register", json={
        "email": "login@example.com",
        "password": "StrongPass123!",
        "tos_accepted": True,
    })
    resp = await client.post("/auth/login", json={
        "email": "login@example.com",
        "password": "StrongPass123!",
    })
    assert resp.status_code == 200
    # JWT should be in httpOnly cookie, not response body
    cookies = resp.cookies
    assert "access_token" in cookies


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    await client.post("/auth/register", json={
        "email": "wrong@example.com",
        "password": "StrongPass123!",
        "tos_accepted": True,
    })
    resp = await client.post("/auth/login", json={
        "email": "wrong@example.com",
        "password": "WrongPassword!",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_endpoint_with_cookie(client):
    await client.post("/auth/register", json={
        "email": "me@example.com",
        "password": "StrongPass123!",
        "tos_accepted": True,
    })
    await client.post("/auth/login", json={
        "email": "me@example.com",
        "password": "StrongPass123!",
    })
    resp = await client.get("/auth/me")
    assert resp.status_code == 200
    assert resp.json()["email"] == "me@example.com"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/justin/CascadeProjects/clipforge/backend
pytest tests/unit/test_auth.py -v
```

Expected: FAIL (endpoints don't exist yet)

- [ ] **Step 3: Create auth/schemas.py**

```python
from pydantic import BaseModel, EmailStr, field_validator
from uuid import UUID
from datetime import datetime


class UserRegister(BaseModel):
    email: EmailStr
    password: str  # min 8 chars validated in service
    tos_accepted: bool

    @field_validator("tos_accepted")
    @classmethod
    def tos_must_be_accepted(cls, v):
        if not v:
            raise ValueError("Terms of Service must be accepted")
        return v


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: UUID
    email: str
    email_verified: bool
    created_at: datetime

    class Config:
        from_attributes = True
```

- [ ] **Step 4: Create auth/service.py**

Implement:
- `hash_password(password: str) -> str` using passlib bcrypt
- `verify_password(plain: str, hashed: str) -> bool`
- `create_access_token(user_id: UUID) -> str` using python-jose
- `register_user(db, email, password, tos_accepted) -> User` (check duplicate, hash, insert, set `tos_accepted_at=datetime.utcnow()`)
- `authenticate_user(db, email, password) -> User | None`

- [ ] **Step 5: Create auth/dependencies.py**

Implement `get_current_user` FastAPI dependency:
- Extract JWT from `access_token` httpOnly cookie (NOT Authorization header)
- Decode and validate
- Fetch user from DB
- Return user or raise 401

Per CLAUDE.md security non-negotiable: "JWT in httpOnly cookies, never localStorage."

- [ ] **Step 6: Create auth/router.py**

Endpoints:
- `POST /auth/register` → 201 + UserResponse (requires `tos_accepted: true`)
- `POST /auth/login` → 200 + set httpOnly cookie with JWT (SameSite=Lax, Secure in prod, path=/)
- `POST /auth/logout` → 200 + clear cookie
- `GET /auth/me` → 200 + UserResponse (protected, reads JWT from cookie)
- `POST /auth/request-password-reset` → 200 (sends email with reset token — stub email sender for MVP, log token to console)
- `POST /auth/reset-password` → 200 (validates reset token, updates password)
- `POST /auth/verify-email` → 200 (validates email verification token)

Wire router into `app/main.py`.

Note: Email verification and password reset use simple token-based flows. For MVP, the "email" is logged to console/stdout. Real email sending (SendGrid/SES) is deferred to Week 4.

- [ ] **Step 7: Set up tests/conftest.py with test database**

```python
import pytest
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.db.models import Base
from app.db.session import get_db
from app.main import app

TEST_DB_URL = "postgresql+asyncpg://clipforge:clipforge@localhost:5432/clipforge_test"


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(TEST_DB_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def db_session(test_engine):
    session_factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def client(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    from httpx import AsyncClient, ASGITransport
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
```

Create the test database:
```bash
docker exec -it infra-postgres-1 psql -U clipforge -c "CREATE DATABASE clipforge_test;"
```

- [ ] **Step 8: Run tests — should pass**

```bash
pytest tests/unit/test_auth.py -v
```

Expected: all 4 tests PASS

- [ ] **Step 9: Commit**

```bash
git add backend/app/auth/ backend/tests/
git commit -m "feat(auth): add registration, login, and JWT authentication"
```

---

## Chunk 3: File Storage Decision + Video Upload + Validation

### Task 7: DECISION_003 — File Storage Design

**Files:**
- Create: `docs/decisions/DECISION_003_file_storage.md`

- [ ] **Step 1: Write DECISION_003 using the Adversarial Agent Protocol**

Per CLAUDE.md, the protocol is required for "Any file storage decision (upload paths, lifecycle, cleanup)." Key decisions:
- S3 vs R2 for MVP (R2 preferred for no egress fees per CLAUDE.md)
- Upload path structure: `uploads/{user_id}/{uuid}.{ext}`
- Lifecycle policies: auto-delete after 30 days
- Partial upload cleanup: what happens when upload is interrupted at 95%? Temp file cleanup strategy.
- Rendered output storage: separate prefix `rendered/{user_id}/{clip_id}/`
- Signed URL expiry: 1 hour for downloads, 15 minutes for previews
- Local dev: MinIO in docker-compose or mock S3 client in tests?
- Cleanup on account deletion: S3 objects, DB rows, Redis jobs, rendered outputs

- [ ] **Step 2: Commit**

```bash
git add docs/decisions/DECISION_003_file_storage.md
git commit -m "docs(decisions): add DECISION_003 file storage design"
```

---

### Task 8: File Validation (magic bytes + ffprobe)

**Files:**
- Create: `backend/app/videos/__init__.py`
- Create: `backend/app/videos/validation.py`
- Create: `backend/tests/unit/test_validation.py`

- [ ] **Step 1: Write test_validation.py**

```python
import pytest
from app.videos.validation import validate_magic_bytes, validate_with_ffprobe


def test_valid_mp4_magic_bytes(tmp_path):
    # MP4 files start with ftyp at offset 4
    mp4_header = b"\x00\x00\x00\x20ftyp" + b"\x00" * 24
    f = tmp_path / "test.mp4"
    f.write_bytes(mp4_header)
    assert validate_magic_bytes(str(f)) is True


def test_invalid_magic_bytes(tmp_path):
    f = tmp_path / "fake.mp4"
    f.write_bytes(b"this is not a video file")
    assert validate_magic_bytes(str(f)) is False


def test_text_file_rejected(tmp_path):
    f = tmp_path / "script.mp4"
    f.write_bytes(b"#!/bin/bash\nrm -rf /")
    assert validate_magic_bytes(str(f)) is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/test_validation.py -v
```

- [ ] **Step 3: Implement validation.py**

```python
import subprocess
import json
import magic


ALLOWED_MIME_TYPES = {
    "video/mp4",
    "video/quicktime",
    "video/x-msvideo",
    "video/x-matroska",
    "video/webm",
}


def validate_magic_bytes(file_path: str) -> bool:
    """Check file's actual MIME type via libmagic, not extension."""
    try:
        mime = magic.from_file(file_path, mime=True)
        return mime in ALLOWED_MIME_TYPES
    except Exception:
        return False


def validate_with_ffprobe(file_path: str) -> dict | None:
    """Run ffprobe to extract video metadata. Returns dict or None if invalid."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format", "-show_streams",
                file_path,
            ],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return None
        probe = json.loads(result.stdout)
        # Must have at least one video stream
        streams = probe.get("streams", [])
        has_video = any(s["codec_type"] == "video" for s in streams)
        has_audio = any(s["codec_type"] == "audio" for s in streams)
        if not has_video or not has_audio:
            return None
        duration = float(probe["format"].get("duration", 0))
        if duration > 10800:  # 3 hours
            return None
        return {
            "duration": duration,
            "file_size": int(probe["format"].get("size", 0)),
            "streams": streams,
        }
    except Exception:
        return None
```

- [ ] **Step 4: Run tests — should pass**

```bash
pytest tests/unit/test_validation.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/videos/validation.py backend/tests/unit/test_validation.py
git commit -m "feat(upload): add magic bytes and ffprobe validation"
```

---

### Task 9: S3/R2 Storage Client

**Files:**
- Create: `backend/app/videos/storage.py`
- Create: `backend/tests/unit/test_storage.py` (unit test with mocked S3)

- [ ] **Step 1: Write test_storage.py**

Test `generate_s3_key` produces a user-scoped key, and test `generate_presigned_url` calls boto3 correctly (mock boto3).

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement storage.py**

```python
import boto3
from uuid import UUID, uuid4
from app.config import settings


def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url or None,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name=settings.s3_region,
    )


def generate_s3_key(user_id: UUID, original_filename: str) -> str:
    """User-scoped S3 key: uploads/{user_id}/{uuid}.{ext}"""
    ext = original_filename.rsplit(".", 1)[-1] if "." in original_filename else "mp4"
    return f"uploads/{user_id}/{uuid4()}.{ext}"


async def upload_file_to_s3(file_path: str, s3_key: str) -> None:
    client = get_s3_client()
    client.upload_file(file_path, settings.s3_bucket_name, s3_key)


def generate_presigned_url(s3_key: str, expires_in: int = 3600) -> str:
    client = get_s3_client()
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket_name, "Key": s3_key},
        ExpiresIn=expires_in,
    )


async def delete_s3_object(s3_key: str) -> None:
    client = get_s3_client()
    client.delete_object(Bucket=settings.s3_bucket_name, Key=s3_key)
```

- [ ] **Step 4: Run tests — should pass**

- [ ] **Step 5: Commit**

```bash
git add backend/app/videos/storage.py backend/tests/unit/test_storage.py
git commit -m "feat(upload): add S3/R2 storage client with user-scoped keys"
```

---

### Task 10: Upload Endpoint

**Files:**
- Create: `backend/app/videos/schemas.py`
- Create: `backend/app/videos/service.py`
- Create: `backend/app/videos/router.py`
- Create: `backend/tests/unit/test_upload.py`

- [ ] **Step 1: Write test_upload.py**

Tests:
- `test_upload_valid_video` — POST multipart file, get 201 with video metadata
- `test_upload_too_large` — reject > 500MB with 413
- `test_upload_invalid_type` — reject non-video with 415
- `test_upload_unauthenticated` — 401 without token
- `test_list_my_videos` — only see own videos
- `test_upload_rate_limit` — 6th upload in an hour gets 429

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Create videos/schemas.py**

```python
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime


class VideoResponse(BaseModel):
    id: UUID
    original_filename: str
    file_size: int
    duration: float | None
    status: str
    uploaded_at: datetime

    class Config:
        from_attributes = True


class VideoListResponse(BaseModel):
    videos: list[VideoResponse]
    total: int
```

- [ ] **Step 4: Create videos/service.py**

Implement:
- `upload_video(db, user, file)`:
  1. Check rate limit (5/hour per user)
  2. Save to temp file (use `tempfile.NamedTemporaryFile` with cleanup in `finally` block)
  3. Validate magic bytes — if invalid, clean up temp file and return 415
  4. Validate with ffprobe (get duration, verify audio track) — if invalid, clean up and return 422
  5. Generate S3 key, upload to S3
  6. Create `Video` DB record with status=uploaded
  7. Clean up temp file in `finally` block (handles interrupted uploads)
  8. Return video record
  Important: wrap entire flow in try/finally to ensure temp file cleanup even on partial upload or crash.
- `list_user_videos(db, user_id)` — always scoped to user_id
- `get_user_video(db, user_id, video_id)` — always scoped to user_id

- [ ] **Step 5: Create videos/router.py**

Endpoints:
- `POST /videos/upload` — multipart upload, requires auth
- `GET /videos/` — list user's videos, requires auth
- `GET /videos/{video_id}` — get single video, requires auth (user-scoped)
- `DELETE /videos/{video_id}` — soft delete + queue S3 cleanup, requires auth

Wire router into `app/main.py`.

- [ ] **Step 6: Run tests — should pass**

```bash
pytest tests/unit/test_upload.py -v
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/videos/ backend/tests/unit/test_upload.py
git commit -m "feat(upload): add video upload endpoint with validation and S3 storage"
```

---

## Chunk 4: Job Queue + Transcription

### Task 11: ARQ Worker Scaffold

**Files:**
- Create: `backend/app/jobs/__init__.py`
- Create: `backend/app/jobs/worker.py`
- Create: `backend/app/jobs/tasks.py`
- Create: `backend/app/jobs/router.py`
- Create: `backend/app/jobs/schemas.py`
- Create: `backend/tests/unit/test_jobs.py`

- [ ] **Step 1: Write test_jobs.py**

Tests:
- `test_get_job_status` — create a job, query status endpoint, get pending
- `test_job_not_found` — 404 for nonexistent job
- `test_job_scoped_to_user` — user A can't see user B's job

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Create jobs/schemas.py**

```python
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime


class JobResponse(BaseModel):
    id: UUID
    job_type: str
    status: str
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    class Config:
        from_attributes = True
```

- [ ] **Step 4: Create jobs/worker.py**

```python
from arq import create_pool
from arq.connections import RedisSettings
from app.config import settings
from app.jobs.tasks import transcribe_video


async def startup(ctx):
    """ARQ worker startup — initialize DB session."""
    pass


async def shutdown(ctx):
    """ARQ worker shutdown."""
    pass


class WorkerSettings:
    functions = [transcribe_video]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 3
    job_timeout = 1800  # 30 minutes
```

- [ ] **Step 5: Create jobs/tasks.py (stub)**

```python
async def transcribe_video(ctx, video_id: str, user_id: str):
    """Placeholder — implemented in Task 11."""
    pass
```

- [ ] **Step 6: Create jobs/router.py**

Endpoints:
- `GET /jobs/{job_id}` — returns job status (user-scoped)
- `GET /jobs/video/{video_id}` — returns all jobs for a video (user-scoped)

Wire router into `app/main.py`.

- [ ] **Step 7: Run tests — should pass**

- [ ] **Step 8: Commit**

```bash
git add backend/app/jobs/ backend/tests/unit/test_jobs.py
git commit -m "feat(jobs): add ARQ worker scaffold and job status endpoints"
```

---

### Task 12: DECISION_004 — Transcription Pipeline

**Files:**
- Create: `docs/decisions/DECISION_004_transcription_pipeline.md`

- [ ] **Step 1: Write DECISION_004 using the Adversarial Agent Protocol**

Key decisions:
- Audio extraction: FFmpeg → WAV or MP3 before sending to Whisper?
- Whisper model: `whisper-1` vs local Whisper
- **Long video handling: Whisper has 25MB file limit** — need chunking strategy for long audio. Options:
  - Split audio into ≤25MB chunks with overlap, send each to Whisper, merge transcripts
  - Use lower bitrate extraction to keep file size down (mono, 64kbps)
  - Reject videos whose extracted audio exceeds 25MB (poor UX for 2+ hour videos)
- Transcript storage: encrypted at rest vs delete after clip detection
- Word-level timestamps: request `timestamp_granularities=["word"]` from Whisper API
- Error handling: what if Whisper returns partial transcript? Retry strategy?
- Cost: ~$0.006/minute — a 3-hour video costs ~$1.08

- [ ] **Step 2: Commit**

```bash
git add docs/decisions/DECISION_004_transcription_pipeline.md
git commit -m "docs(decisions): add DECISION_004 transcription pipeline"
```

---

### Task 13: Whisper Integration — Audio Extraction + Transcription

**Files:**
- Create: `backend/app/transcription/__init__.py`
- Create: `backend/app/transcription/audio.py`
- Create: `backend/app/transcription/service.py`
- Create: `backend/app/transcription/router.py`
- Create: `backend/app/transcription/schemas.py`
- Create: `backend/tests/unit/test_transcription.py`

- [ ] **Step 1: Write test for audio extraction**

```python
import pytest
from unittest.mock import patch, MagicMock
from app.transcription.audio import extract_audio


def test_extract_audio_generates_ffmpeg_command():
    """Verify FFmpeg is called with correct args for audio extraction."""
    with patch("app.transcription.audio.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        output = extract_audio("/input/video.mp4", "/output/audio.mp3")
        assert output == "/output/audio.mp3"
        cmd = mock_run.call_args[0][0]
        assert "ffmpeg" in cmd[0]
        assert "-vn" in cmd  # no video
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement transcription/audio.py**

```python
import subprocess
import os


def extract_audio(video_path: str, output_path: str) -> str:
    """Extract audio from video as MP3 for Whisper API."""
    subprocess.run(
        [
            "ffmpeg", "-i", video_path,
            "-vn", "-acodec", "libmp3lame", "-q:a", "4",
            "-y", output_path,
        ],
        capture_output=True, check=True, timeout=600,
    )
    if not os.path.exists(output_path):
        raise RuntimeError(f"Audio extraction failed: {output_path} not created")
    return output_path
```

- [ ] **Step 4: Run tests — should pass**

- [ ] **Step 5: Write test for Whisper service (mocked API)**

```python
@pytest.mark.asyncio
async def test_transcribe_calls_whisper(mock_openai):
    """Verify Whisper API is called and response is parsed."""
    result = await transcribe_audio("/path/to/audio.mp3")
    assert result["text"] is not None
    assert "words" in result
```

- [ ] **Step 6: Implement transcription/service.py with chunking support**

Must handle audio files > 25MB (Whisper API limit). Implementation per DECISION_004:
- Check file size of extracted audio
- If ≤ 25MB: send directly to Whisper API
- If > 25MB: split into chunks using FFmpeg (with 1s overlap), transcribe each, merge results with timestamp offset correction

```python
import openai
import os
from app.config import settings

MAX_WHISPER_FILE_SIZE = 25 * 1024 * 1024  # 25MB


async def transcribe_audio(audio_path: str) -> dict:
    """Send audio to Whisper API, return transcript with word timestamps.
    Handles files > 25MB by chunking."""
    file_size = os.path.getsize(audio_path)
    if file_size <= MAX_WHISPER_FILE_SIZE:
        return await _transcribe_single(audio_path)
    else:
        return await _transcribe_chunked(audio_path)


async def _transcribe_single(audio_path: str) -> dict:
    client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
    with open(audio_path, "rb") as f:
        response = await client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            response_format="verbose_json",
            timestamp_granularities=["word"],
        )
    return {
        "text": response.text,
        "words": [
            {"word": w.word, "start": w.start, "end": w.end}
            for w in (response.words or [])
        ],
        "language": response.language,
    }


async def _transcribe_chunked(audio_path: str) -> dict:
    """Split audio into chunks, transcribe each, merge with offset correction."""
    # Implementation: use FFmpeg to split into N-minute segments
    # Transcribe each segment, adjust timestamps by chunk offset
    # Merge text and word arrays
    # Details determined by DECISION_004
    pass
```

- [ ] **Step 7: Wire transcribe_video job task (update jobs/tasks.py)**

Full implementation:
1. Fetch video record from DB
2. Download video from S3 to temp file
3. Extract audio with FFmpeg
4. Send to Whisper API
5. Store transcript + word_timestamps in DB
6. Update video status to "ready"
7. Update job status to "completed"
8. Clean up temp files
9. On any error: update job status to "failed" with error_message, clean up

- [ ] **Step 8: Create transcription/router.py**

Endpoints:
- `GET /transcripts/{video_id}` — get transcript for a video (user-scoped)

Wire router into `app/main.py`.

- [ ] **Step 9: Trigger transcription on upload**

Update `videos/service.py` `upload_video` to:
1. After successful upload, create a `Job` record (type=transcribe, status=pending)
2. Enqueue the ARQ task with `video_id` and `user_id`
3. Return the `job_id` in the upload response

- [ ] **Step 10: Run all tests**

```bash
pytest tests/ -v
```

- [ ] **Step 11: Commit**

```bash
git add backend/app/transcription/ backend/app/jobs/tasks.py backend/app/videos/service.py backend/tests/unit/test_transcription.py
git commit -m "feat(transcribe): integrate Whisper API with audio extraction and job queue"
```

---

## Chunk 5: Basic React Frontend

### Task 14: React + Vite Scaffold

**Files:**
- Create: `frontend/` (via `npm create vite`)

- [ ] **Step 1: Scaffold React + TypeScript project**

```bash
cd /Users/justin/CascadeProjects/clipforge
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
npm install axios react-router-dom@6
npm install -D @types/react-router-dom
```

- [ ] **Step 2: Verify dev server starts**

```bash
cd frontend && npm run dev
# Ctrl+C after confirming it starts
```

- [ ] **Step 3: Commit**

```bash
git add frontend/
git commit -m "chore(frontend): scaffold React + Vite + TypeScript project"
```

---

### Task 15: API Client + Auth Pages

**Files:**
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/components/Auth/LoginForm.tsx`
- Create: `frontend/src/components/Auth/RegisterForm.tsx`
- Create: `frontend/src/pages/LoginPage.tsx`
- Create: `frontend/src/pages/RegisterPage.tsx`

- [ ] **Step 1: Create api/client.ts**

```typescript
import axios from "axios";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "http://localhost:8000",
  withCredentials: true, // Send httpOnly cookies with every request
});

export default api;
```

JWT is in httpOnly cookies set by the backend — no token in localStorage per CLAUDE.md security requirements. The `withCredentials: true` flag ensures cookies are sent cross-origin.

- [ ] **Step 2: Create RegisterForm and LoginForm components**

Simple forms with email + password fields, error display, redirect on success.

- [ ] **Step 3: Create LoginPage and RegisterPage**

Page wrappers that render the forms, centered layout.

- [ ] **Step 4: Set up React Router in App.tsx**

Routes:
- `/login` → LoginPage
- `/register` → RegisterPage
- `/dashboard` → DashboardPage (protected, redirect if no token)
- `/` → redirect to `/dashboard`

- [ ] **Step 5: Manual test — register + login flow works**

- [ ] **Step 6: Commit**

```bash
git add frontend/src/
git commit -m "feat(frontend): add auth pages with login and registration forms"
```

---

### Task 16: Upload Flow + Job Progress UI

**Files:**
- Create: `frontend/src/components/VideoUpload/UploadDropzone.tsx`
- Create: `frontend/src/components/VideoUpload/JobProgress.tsx`
- Create: `frontend/src/pages/DashboardPage.tsx`

- [ ] **Step 1: Create UploadDropzone component**

Drag-and-drop or click-to-select file upload. Shows:
- File name and size before upload
- Upload progress bar during upload
- "Processing..." state after upload completes (job enqueued)

Uses `POST /videos/upload` with multipart form data.

- [ ] **Step 2: Create JobProgress component**

Polls `GET /jobs/{job_id}` every 3 seconds while status is `pending` or `running`.
Shows:
- Spinner + "Transcribing your video..." while running
- Green check + "Ready" when completed
- Red X + error message when failed

Stops polling when terminal state reached.

- [ ] **Step 3: Create DashboardPage**

Layout:
- Upload zone at top
- List of user's videos below (from `GET /videos/`)
- Each video card shows: filename, duration, status, latest job status

- [ ] **Step 4: Add CORS middleware to FastAPI**

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

- [ ] **Step 5: Manual end-to-end test**

1. Start backend: `uvicorn app.main:app --reload`
2. Start frontend: `npm run dev`
3. Register → Login → Upload video → See job progress → See transcript

- [ ] **Step 6: Commit**

```bash
git add frontend/src/ backend/app/main.py
git commit -m "feat(frontend): add video upload dropzone and job progress polling"
```

---

### Task 17: Build Log + Week 1 Tag

- [ ] **Step 1: Update docs/build_log.md with all work completed**

- [ ] **Step 2: Final commit**

```bash
git add docs/build_log.md
git commit -m "docs: update build log for Week 1 completion"
```

- [ ] **Step 3: Merge to main and tag**

```bash
git checkout -b main
git merge develop
git tag -a v0.1.0 -m "feat: upload pipeline, transcription, auth, basic UI"
git checkout develop
```

---

## Dependency Graph

```
Task 1 (scaffold) → Task 2 (docker) → Task 3 (DECISION_001) → Task 4 (models)
                                                                       ↓
Task 5 (DECISION_002 auth) → Task 6 (auth impl) ──────────→ Task 10 (upload endpoint)
Task 7 (DECISION_003 storage) → Task 9 (S3 client) ───────→ Task 10 (upload endpoint)
Task 8 (validation) ──────────────────────────────────────→ Task 10 (upload endpoint)
                                                                       ↓
Task 11 (ARQ scaffold) → Task 12 (DECISION_004) → Task 13 (transcription)
                                                                       ↓
Task 14 (React scaffold) → Task 15 (auth pages) → Task 16 (upload UI + progress)
                                                                       ↓
                                                              Task 17 (tag v0.1.0)
```

**Parallelizable tasks:**
- Tasks 5+6 (auth), 7+8+9 (storage/validation) can be built in parallel after Task 4
- Task 14 (React scaffold) can start as soon as Task 6 is done (needs auth endpoints)
- Task 11 (ARQ) can start after Task 4 (only needs models)

---

## Risk Notes

1. **S3/R2 in local dev:** For local development without R2, use MinIO (`minio/minio` Docker image) or mock the S3 client in tests. Add MinIO to docker-compose as an optional service.
2. **Whisper 25MB limit:** For videos > ~25 min, audio extraction produces files > 25MB. DECISION_004 must address chunking.
3. **Test database isolation:** Each test must roll back its transaction to avoid cross-test contamination.
4. **FFmpeg dependency:** Tests that call `ffprobe` or `ffmpeg` need it installed. CI must have it. Local dev assumes it's present.
