"""
Celery Application for Learning Hub Worker
"""
import os
import ssl
from celery import Celery

# Redis connection
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")

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
    task_time_limit=360,          # 6 minutes max limit
    task_soft_time_limit=300,     # 5 minutes soft limit
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=100,
    task_acks_late=True,
    worker_concurrency=int(os.getenv("CELERY_CONCURRENCY", "4")),
)

if BROKER_URL.startswith("rediss://"):
    celery_app.conf.update(broker_use_ssl={"ssl_cert_reqs": ssl.CERT_NONE})

if REDIS_URL.startswith("rediss://"):
    celery_app.conf.update(redis_backend_use_ssl={"ssl_cert_reqs": ssl.CERT_NONE})

if __name__ == "__main__":
    celery_app.start()
