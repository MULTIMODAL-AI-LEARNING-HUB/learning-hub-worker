"""MinIO client wrapper."""

from minio import Minio
from src.core.config import settings

_client: Minio | None = None


def get_minio_client() -> Minio:
    global _client
    if _client is None:
        endpoint = settings.MINIO_ENDPOINT
        if endpoint.startswith("https://"):
            endpoint = endpoint[len("https://"):]
        elif endpoint.startswith("http://"):
            endpoint = endpoint[len("http://"):]
        endpoint = endpoint.rstrip("/")

        _client = Minio(
            endpoint,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        _ensure_bucket(_client)
    return _client


def _ensure_bucket(client: Minio) -> None:
    bucket = settings.MINIO_BUCKET_NAME
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)


def upload_file(object_name: str, data, content_type: str = "application/octet-stream", length: int = -1) -> str:
    client = get_minio_client()
    client.put_object(
        settings.MINIO_BUCKET_NAME,
        object_name,
        data,
        length=length,
        content_type=content_type,
    )
    return f"s3://{settings.MINIO_BUCKET_NAME}/{object_name}"


def download_file(object_name: str):
    client = get_minio_client()
    return client.get_object(settings.MINIO_BUCKET_NAME, object_name)


def delete_file(object_name: str) -> None:
    client = get_minio_client()
    client.remove_object(settings.MINIO_BUCKET_NAME, object_name)
