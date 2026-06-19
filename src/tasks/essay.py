"""Essay grading task."""

import json

from celery_app import celery_app


@celery_app.task(name="grade_essay_task", bind=True, max_retries=2)
def grade_essay_task(self, document_id: str, submission_id: str, essay_text: str) -> dict:
    """Grade essay by comparing with source document context."""
    try:
        from src.utils.qdrant_client import search_similar
        from src.utils.embeddings import generate_embedding

        query_vector = generate_embedding(essay_text[:512])
        results = search_similar(query_vector, document_id=document_id, limit=5)
        context = "\n".join([r["payload"]["text"] for r in results]) if results else ""

        import httpx
        from src.core.config import settings

        response = httpx.post(
            f"{settings.AI_SERVICE_URL}/study/essay/grade",
            headers={"X-Internal-API-Key": settings.INTERNAL_API_KEY},
            json={
                "context": context,
                "essay_text": essay_text,
            },
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()

        _update_submission(submission_id, data.get("score", 0), data.get("feedback", ""), json.dumps(data))

        return {"status": "completed", "grade": data}

    except Exception as exc:
        raise self.retry(exc=exc, countdown=30)


def _update_submission(submission_id: str, score: float, feedback: str, raw_json: str) -> None:
    try:
        import psycopg2
        from src.core.config import settings

        conn = psycopg2.connect(settings.DATABASE_URL.replace("+asyncpg", ""))
        cur = conn.cursor()
        cur.execute(
            "UPDATE essay_submissions SET ai_grade = %s, ai_feedback = %s WHERE id = %s",
            (score, feedback, submission_id),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass
