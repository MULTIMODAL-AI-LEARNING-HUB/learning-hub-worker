"""Document task entry point."""

from celery_app import celery_app


@celery_app.task(name="process_document_task", bind=True, max_retries=3)
def process_document_task(self, document_id: str) -> dict:
    """Delegate to document_processing module."""
    from src.tasks.document_processing import process_document_task as _process

    return _process(document_id)
