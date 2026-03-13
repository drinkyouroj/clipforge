from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db.models import Transcript, User, Video
from app.db.session import get_db
from app.transcription.schemas import TranscriptResponse

router = APIRouter(prefix="/transcripts", tags=["transcripts"])


@router.get("/{video_id}", response_model=TranscriptResponse)
async def get_transcript(
    video_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Verify video belongs to user
    video_result = await db.execute(
        select(Video).where(Video.id == video_id, Video.user_id == user.id)
    )
    video = video_result.scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    result = await db.execute(
        select(Transcript).where(Transcript.video_id == video_id)
    )
    transcript = result.scalar_one_or_none()
    if not transcript:
        raise HTTPException(status_code=404, detail="Transcript not found")
    return transcript
