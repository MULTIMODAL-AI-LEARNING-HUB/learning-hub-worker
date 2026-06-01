"""Flashcard generation task."""

from celery_app import celery_app


@celery_app.task(name="generate_flashcards_task", bind=True, max_retries=2)
def generate_flashcards_task(self, document_id: str, set_name: str, count: int = 20) -> dict:
    """Generate flashcards from document context."""
    try:
        from src.utils.qdrant_client import search_similar
        from src.utils.embeddings import generate_embedding

        query_vector = generate_embedding(f"flashcards about document {document_id}")
        results = search_similar(query_vector, document_id=document_id, limit=5)
        context = "\n".join([r["payload"]["text"] for r in results]) if results else ""

        import httpx
        from src.core.config import settings

        response = httpx.post(
            f"{settings.AI_SERVICE_URL}/study/flashcards/generate",
            json={
                "context": context,
                "set_name": set_name,
                "count": count,
            },
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()

        return {"status": "completed", "flashcards": data.get("items", [])}

    except Exception as exc:
        self.retry(exc=exc, countdown=30)
