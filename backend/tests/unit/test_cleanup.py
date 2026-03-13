"""Tests for daily cleanup task."""

from datetime import datetime, timezone, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.db.models import Clip, Export, Job, Transcript, User, Video


@pytest_asyncio.fixture
async def old_video(db_session):
    """Create a video older than 30 days."""
    user = User(
        email="cleanup@example.com",
        hashed_password="hashed",
        tos_accepted_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    await db_session.flush()

    video = Video(
        user_id=user.id,
        original_filename="old.mp4",
        s3_key=f"uploads/{user.id}/old.mp4",
        file_size=1024,
        duration=60.0,
        status="ready",
        created_at=datetime.now(timezone.utc) - timedelta(days=31),
    )
    db_session.add(video)
    await db_session.commit()
    return user, video


@pytest_asyncio.fixture
async def soft_deleted_video(db_session):
    """Create a video soft-deleted 8 days ago."""
    user = User(
        email="purge@example.com",
        hashed_password="hashed",
        tos_accepted_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    await db_session.flush()

    video = Video(
        user_id=user.id,
        original_filename="deleted.mp4",
        s3_key=f"uploads/{user.id}/deleted.mp4",
        file_size=1024,
        duration=60.0,
        status="deleted",
        deleted_at=datetime.now(timezone.utc) - timedelta(days=8),
    )
    db_session.add(video)
    await db_session.commit()
    return user, video


@pytest_asyncio.fixture
async def user_with_expired_period(db_session):
    """Create a user with expired billing period."""
    user = User(
        email="expired@example.com",
        hashed_password="hashed",
        tos_accepted_at=datetime.now(timezone.utc),
        subscription_tier="free",
        period_exports_used=7,
        current_period_end=datetime.now(timezone.utc) - timedelta(days=1),
    )
    db_session.add(user)
    await db_session.commit()
    return user


@pytest.mark.asyncio
async def test_auto_expire_old_videos(old_video, db_session):
    """Videos older than 30 days should be auto-expired."""
    from unittest.mock import patch, AsyncMock
    from app.jobs.tasks import cleanup_expired_content

    user, video = old_video
    video_id = video.id

    with patch("app.jobs.tasks._get_db_session", return_value=db_session), \
         patch("app.jobs.tasks.delete_s3_object", new_callable=AsyncMock):
        await cleanup_expired_content(None)

    # Re-query since cleanup closed the session — need a fresh lookup
    result = await db_session.execute(select(Video).where(Video.id == video_id))
    updated = result.scalar_one_or_none()
    assert updated is not None
    assert updated.status == "deleted"
    assert updated.deleted_at is not None


@pytest.mark.asyncio
async def test_hard_delete_old_soft_deleted(soft_deleted_video, db_session):
    """Soft-deleted videos older than 7 days should be hard-deleted."""
    from unittest.mock import patch, AsyncMock
    from app.jobs.tasks import cleanup_expired_content

    user, video = soft_deleted_video
    video_id = video.id

    with patch("app.jobs.tasks._get_db_session", return_value=db_session), \
         patch("app.jobs.tasks.delete_s3_object", new_callable=AsyncMock):
        await cleanup_expired_content(None)

    result = await db_session.execute(select(Video).where(Video.id == video_id))
    assert result.scalar_one_or_none() is None  # Hard-deleted


@pytest.mark.asyncio
async def test_reset_expired_billing_periods(user_with_expired_period, db_session):
    """Users with expired periods should have credits reset."""
    from app.jobs.tasks import cleanup_expired_content
    from unittest.mock import patch, AsyncMock

    user = user_with_expired_period
    user_id = user.id

    with patch("app.jobs.tasks._get_db_session", return_value=db_session), \
         patch("app.jobs.tasks.delete_s3_object", new_callable=AsyncMock):
        await cleanup_expired_content(None)

    # Re-query since cleanup closed the session
    result = await db_session.execute(select(User).where(User.id == user_id))
    updated = result.scalar_one_or_none()
    assert updated is not None
    assert updated.period_exports_used == 0
    assert updated.current_period_end > datetime.now(timezone.utc)
