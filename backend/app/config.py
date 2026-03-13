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
