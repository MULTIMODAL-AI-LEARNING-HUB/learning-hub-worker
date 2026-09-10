"""Quiz generation task."""

import logging

from celery_app import celery_app

logger = logging.getLogger("worker.quiz")


@celery_app.task(name="generate_quiz_task", bind=True, max_retries=3, default_retry_delay=10)
def generate_quiz_task(self, document_id: str, quiz_type: str = "quick", question_count: int = 5) -> dict:
    """Generate quiz questions from stratified full-document context."""
    try:
        from src.utils.study_context import build_document_context

        # Stratified sampling across head/middle/tail so questions span the
        # whole document instead of 5 random UUID-noise chunks.
        context, total_chunks = build_document_context(document_id)
        if not context:
            return {"status": "error", "message": "Document has no indexed content yet"}

        import httpx
        from src.core.config import settings

        response = httpx.post(
            f"{settings.AI_SERVICE_URL}/study/quiz/generate",
            headers={"X-Internal-API-Key": settings.INTERNAL_API_KEY},
            json={
                "context": context,
                "quiz_type": quiz_type,
                "question_count": question_count,
                "coverage_chunks": total_chunks,
            },
            timeout=120,
        )
        response.raise_for_status()
        data = response.json()

        return {"status": "completed", "questions": data.get("questions", [])}

    except Exception as exc:
        logger.warning("generate_quiz_task failed for %s: %s", document_id, exc)
        raise self.retry(exc=exc, countdown=15)
