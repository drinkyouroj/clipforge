import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "subscription_tier IN ('free', 'starter', 'pro')",
            name="ck_users_subscription_tier",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    email_verified = Column(Boolean, default=False, nullable=False)
    email_verification_token = Column(String(255), nullable=True)
    password_reset_token = Column(String(255), nullable=True)
    password_reset_expires = Column(DateTime(timezone=True), nullable=True)
    tos_accepted_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Billing
    stripe_customer_id = Column(String(255), nullable=True, unique=True)
    subscription_tier = Column(String(20), nullable=False, default="free")
    subscription_stripe_id = Column(String(255), nullable=True)
    current_period_end = Column(DateTime(timezone=True), nullable=True)
    period_exports_used = Column(Integer, nullable=False, default=0)

    videos = relationship("Video", back_populates="user")
    jobs = relationship("Job", back_populates="user")
    exports = relationship("Export", back_populates="user")


class Video(Base):
    __tablename__ = "videos"
    __table_args__ = (
        CheckConstraint(
            "status IN ('uploaded', 'processing', 'ready', 'failed', 'deleted')",
            name="ck_videos_status",
        ),
        Index("ix_videos_user_active", "user_id", "created_at", postgresql_where="deleted_at IS NULL"),
        Index("ix_videos_user_status", "user_id", "status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    original_filename = Column(String(255), nullable=False)
    s3_key = Column(String(512), nullable=False)
    file_size = Column(BigInteger, nullable=False)
    duration = Column(Float, nullable=True)
    mime_type = Column(String(100), nullable=True)
    status = Column(String(20), nullable=False, default="uploaded")
    uploaded_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="videos")
    transcript = relationship("Transcript", back_populates="video", uselist=False)
    clips = relationship("Clip", back_populates="video")
    jobs = relationship("Job", back_populates="video")


class Transcript(Base):
    __tablename__ = "transcripts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    video_id = Column(UUID(as_uuid=True), ForeignKey("videos.id"), unique=True, nullable=False)
    content = Column(Text, nullable=False)
    word_timestamps = Column(JSONB, nullable=False, default=list)
    whisper_model = Column(String(50), default="whisper-1")
    language = Column(String(10), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    video = relationship("Video", back_populates="transcript")
    clips = relationship("Clip", back_populates="transcript")


class Clip(Base):
    __tablename__ = "clips"
    __table_args__ = (
        CheckConstraint(
            "status IN ('candidate', 'selected', 'rendering', 'rendered', 'failed')",
            name="ck_clips_status",
        ),
        Index("ix_clips_video_score", "video_id", "virality_score"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    video_id = Column(UUID(as_uuid=True), ForeignKey("videos.id"), nullable=False)
    transcript_id = Column(UUID(as_uuid=True), ForeignKey("transcripts.id"), nullable=True)
    start_time = Column(Float, nullable=False)
    end_time = Column(Float, nullable=False)
    duration = Column(Float, nullable=False)
    virality_score = Column(Integer, nullable=True)
    hook = Column(Text, nullable=True)
    reasoning = Column(Text, nullable=True)
    clip_type = Column(String(30), nullable=True)
    suggested_title = Column(String(100), nullable=True)
    platform_fit = Column(JSONB, nullable=True)
    status = Column(String(20), nullable=False, default="candidate")
    rendered_s3_key = Column(String(512), nullable=True)
    face_track = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    video = relationship("Video", back_populates="clips")
    transcript = relationship("Transcript", back_populates="clips")
    exports = relationship("Export", back_populates="clip")


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "job_type IN ('transcribe', 'detect_clips', 'render')",
            name="ck_jobs_job_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_jobs_status",
        ),
        Index("ix_jobs_user_created", "user_id", "created_at"),
        Index("ix_jobs_video_type", "video_id", "job_type"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    video_id = Column(UUID(as_uuid=True), ForeignKey("videos.id"), nullable=False)
    job_type = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    render_context = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="jobs")
    video = relationship("Video", back_populates="jobs")


class Export(Base):
    __tablename__ = "exports"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'rendering', 'rendered', 'failed')",
            name="ck_exports_status",
        ),
        Index("ix_exports_user_created", "user_id", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    clip_id = Column(UUID(as_uuid=True), ForeignKey("clips.id"), nullable=False)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    platform = Column(String(30), nullable=False)
    aspect_ratio = Column(String(10), nullable=False)
    resolution = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    s3_key = Column(String(512), nullable=True)
    download_url = Column(Text, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    clip = relationship("Clip", back_populates="exports")
    user = relationship("User", back_populates="exports")
    job = relationship("Job", backref="export")
