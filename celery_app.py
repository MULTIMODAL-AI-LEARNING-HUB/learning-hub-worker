"""
Celery Application for Learning Hub Worker
"""
import os
import ssl
from celery import Celery
from dotenv import load_dotenv

load_dotenv()


def _required_url(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} must be configured; refusing to use an unauthenticated Redis default")
    debug = os.getenv("DEBUG", "false").lower() in {"1", "true", "yes", "on"}
    if not debug and (value.startswith("redis://localhost") or value.startswith("redis://127.0.0.1")):
        raise RuntimeError(f"{name} points to unauthenticated local Redis; configure a protected Redis URL")
    return value


REDIS_URL = _required_url("REDIS_URL")
BROKER_URL = _required_url("CELERY_BROKER_URL")

# Create Celery app
celery_app = Celery(
    "learning_hub_worker",
    broker=BROKER_URL,
    backend=REDIS_URL,
    include=[
        "src.tasks.document_processing",
        "src.tasks.lesson_content",
        "src.tasks.course_file",
        "src.tasks.quiz",
        "src.tasks.essay",
        "src.tasks.flashcards",
        "src.tasks.course_quiz",
    ]
)

# Celery configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=600,          # 10 minutes max limit for large files/transcriptions
    task_soft_time_limit=540,     # 9 minutes soft limit
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=20, # Recycle worker child to prevent PyTorch memory leaks
    task_acks_late=True,
    worker_concurrency=int(os.getenv("CELERY_CONCURRENCY", "2")),
)

if BROKER_URL.startswith("rediss://"):
    # Heroku Data for Redis uses self-signed certificates
    celery_app.conf.update(broker_use_ssl={"ssl_cert_reqs": ssl.CERT_NONE})

if REDIS_URL.startswith("rediss://"):
    celery_app.conf.update(redis_backend_use_ssl={"ssl_cert_reqs": ssl.CERT_NONE})

if __name__ == "__main__":
    celery_app.start()
