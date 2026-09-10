"""Flashcard generation task."""

import logging

from celery_app import celery_app

logger = logging.getLogger("worker.flashcards")


@celery_app.task(name="generate_flashcards_task", bind=True, max_retries=3, default_retry_delay=10)
def generate_flashcards_task(self, flashcard_id: str, document_id: str, set_name: str, count: int = 20) -> dict:
    """Generate flashcards from stratified full-document context."""
    try:
        from src.utils.study_context import build_document_context

        # Stratified sampling so cards test concepts from all chapters,
        # not just the first few paragraphs.
        context, total_chunks = build_document_context(document_id)
        if not context:
            return {"status": "error", "message": "Document has no indexed content yet"}

        import httpx
        from src.core.config import settings

        response = httpx.post(
            f"{settings.AI_SERVICE_URL}/study/flashcards/generate",
            headers={"X-Internal-API-Key": settings.INTERNAL_API_KEY},
            json={
                "context": context,
                "set_name": set_name,
                "count": count,
                "coverage_chunks": total_chunks,
            },
            timeout=120,
        )
        response.raise_for_status()
        data = response.json()
        items = data.get("items", [])

        # Store in Database
        if items:
            import psycopg2
            import uuid

            conn = psycopg2.connect(settings.DATABASE_URL.replace("+asyncpg", ""))
            cur = conn.cursor()

            insert_query = (
                "INSERT INTO flashcard_items (id, flashcard_id, front_text, back_text) "
                "VALUES (%s, %s, %s, %s)"
            )
            insert_data = [
                (str(uuid.uuid4()), flashcard_id, item.get("front", ""), item.get("back", ""))
                for item in items
            ]
            cur.executemany(insert_query, insert_data)
            conn.commit()
            conn.close()

        return {"status": "completed", "flashcards": items}

    except Exception as exc:
        logger.warning("generate_flashcards_task failed for %s: %s", document_id, exc)
        raise self.retry(exc=exc, countdown=15)
