from app.db.models import User, Video, Transcript, Clip, Job, Export


def test_user_model_has_required_fields():
    assert hasattr(User, "id")
    assert hasattr(User, "email")
    assert hasattr(User, "hashed_password")
    assert hasattr(User, "tos_accepted_at")
    assert hasattr(User, "email_verified")
    assert hasattr(User, "is_active")
    assert hasattr(User, "email_verification_token")
    assert hasattr(User, "password_reset_token")
    assert hasattr(User, "password_reset_expires")


def test_video_model_has_soft_delete():
    assert hasattr(Video, "deleted_at")
    assert hasattr(Video, "user_id")
    assert hasattr(Video, "status")
    assert hasattr(Video, "s3_key")


def test_transcript_model_has_word_timestamps():
    assert hasattr(Transcript, "word_timestamps")
    assert hasattr(Transcript, "video_id")
    assert hasattr(Transcript, "content")
    assert hasattr(Transcript, "whisper_model")


def test_clip_model_has_virality_fields():
    assert hasattr(Clip, "virality_score")
    assert hasattr(Clip, "hook")
    assert hasattr(Clip, "reasoning")
    assert hasattr(Clip, "clip_type")
    assert hasattr(Clip, "platform_fit")
    assert hasattr(Clip, "rendered_s3_key")


def test_job_model_has_status_tracking():
    assert hasattr(Job, "job_type")
    assert hasattr(Job, "status")
    assert hasattr(Job, "error_message")
    assert hasattr(Job, "started_at")
    assert hasattr(Job, "completed_at")


def test_export_model_has_platform_fields():
    assert hasattr(Export, "platform")
    assert hasattr(Export, "aspect_ratio")
    assert hasattr(Export, "resolution")
    assert hasattr(Export, "s3_key")
    assert hasattr(Export, "download_url")
    assert hasattr(Export, "expires_at")
