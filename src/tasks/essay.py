from celery_app import celery_app

@celery_app.task(name="grade_essay_task")
def grade_essay_task(*args, **kwargs):
    return {"status": "success", "message": "Stub grade_essay_task completed"}
