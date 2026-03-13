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


async def download_from_s3(s3_key: str, local_path: str) -> None:
    client = get_s3_client()
    client.download_file(settings.s3_bucket_name, s3_key, local_path)


async def delete_s3_object(s3_key: str) -> None:
    client = get_s3_client()
    client.delete_object(Bucket=settings.s3_bucket_name, Key=s3_key)
