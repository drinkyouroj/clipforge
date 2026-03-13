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
