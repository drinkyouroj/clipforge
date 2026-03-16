from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.formparsers import MultiPartParser

from app.config import settings
from app.auth.router import router as auth_router
from app.videos.router import router as videos_router
from app.jobs.router import router as jobs_router
from app.transcription.router import router as transcription_router
from app.clip_detection.router import router as clips_router
from app.export.router import router as exports_router
from app.billing.router import router as billing_router

MultiPartParser.max_file_size = settings.max_upload_size  # 20GB

app = FastAPI(title="ClipForge", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(videos_router)
app.include_router(jobs_router)
app.include_router(transcription_router)
app.include_router(clips_router)
app.include_router(exports_router)
app.include_router(billing_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
