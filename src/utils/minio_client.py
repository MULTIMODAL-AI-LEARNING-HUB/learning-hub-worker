"""MinIO client wrapper."""

import re
from urllib.parse import urlparse

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


def _safe_object_name(value: str) -> str:
    """Normalize an object URI and reject traversal or cross-bucket access."""
    raw = str(value).strip()
    if raw.startswith("s3://"):
        parsed = urlparse(raw)
        if parsed.netloc != settings.MINIO_BUCKET_NAME:
            raise ValueError("Object URI targets an unexpected bucket")
        raw = parsed.path.lstrip("/")

    if not raw or raw.startswith(("/", "\\")) or "\\" in raw:
        raise ValueError("Invalid object storage key")
    parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("Invalid object storage key")
    allowed_prefixes = ("materials/", "course_materials/", "submissions/", "temp/")
    is_document_key = bool(re.fullmatch(r"[0-9a-fA-F-]{36}\.[A-Za-z0-9]+", raw))
    if not raw.startswith(allowed_prefixes) and not is_document_key:
        raise ValueError("Object storage key is outside the allowed namespace")
    return raw


def upload_file(object_name: str, data, content_type: str = "application/octet-stream", length: int = -1) -> str:
    object_name = _safe_object_name(object_name)
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
    return client.get_object(settings.MINIO_BUCKET_NAME, _safe_object_name(object_name))


def delete_file(object_name: str) -> None:
    client = get_minio_client()
    client.remove_object(settings.MINIO_BUCKET_NAME, _safe_object_name(object_name))
