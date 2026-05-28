from celery_app import celery_app

@celery_app.task(name="generate_flashcards_task")
def generate_flashcards_task(*args, **kwargs):
    return {"status": "success", "message": "Stub generate_flashcards_task completed"}
