from celery_app import celery_app

@celery_app.task(name="process_document_task")
def process_document_task(*args, **kwargs):
    return {"status": "success", "message": "Stub process_document_task completed"}
