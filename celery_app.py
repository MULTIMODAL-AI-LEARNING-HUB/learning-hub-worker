"""
Celery Application for Learning Hub Worker
"""
from celery import Celery
import os

# Redis connection
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")

# Create Celery app
celery_app = Celery(
    "learning_hub_worker",
    broker=BROKER_URL,
    backend=REDIS_URL,
    include=[
        "src.tasks.document",
        "src.tasks.quiz",
        "src.tasks.essay",
        "src.tasks.flashcards",
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
    task_time_limit=3600,  # 1 hour max
    task_soft_time_limit=3000,  # 50 minutes soft limit
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=100,
)

if __name__ == "__main__":
    celery_app.start()
