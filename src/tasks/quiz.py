from celery_app import celery_app

@celery_app.task(name="generate_quiz_task")
def generate_quiz_task(*args, **kwargs):
    return {"status": "success", "message": "Stub generate_quiz_task completed"}
