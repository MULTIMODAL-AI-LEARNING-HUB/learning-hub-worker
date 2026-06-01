"""Quiz generation task."""

from celery_app import celery_app


@celery_app.task(name="generate_quiz_task", bind=True, max_retries=2)
def generate_quiz_task(self, document_id: str, quiz_type: str = "quick", question_count: int = 5) -> dict:
    """Generate quiz questions from document context."""
    try:
        _update_status(document_id, "processing")

        from src.utils.qdrant_client import search_similar
        from src.utils.embeddings import generate_embedding

        query_vector = generate_embedding(f"quiz questions about document {document_id}")
        results = search_similar(query_vector, document_id=document_id, limit=5)
        context = "\n".join([r["payload"]["text"] for r in results]) if results else ""

        import httpx
        from src.core.config import settings

        response = httpx.post(
            f"{settings.AI_SERVICE_URL}/study/quiz/generate",
            json={
                "context": context,
                "quiz_type": quiz_type,
                "question_count": question_count,
            },
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()

        _update_status(document_id, "ready")
        return {"status": "completed", "questions": data.get("questions", [])}

    except Exception as exc:
        _update_status(document_id, "failed")
        self.retry(exc=exc, countdown=30)


def _update_status(document_id: str, status: str) -> None:
    try:
        import psycopg2
        from src.core.config import settings

        conn = psycopg2.connect(settings.DATABASE_URL.replace("+asyncpg", ""))
        cur = conn.cursor()
        cur.execute("UPDATE documents SET status = %s WHERE id = %s", (status, document_id))
        conn.commit()
        conn.close()
    except Exception:
        pass
