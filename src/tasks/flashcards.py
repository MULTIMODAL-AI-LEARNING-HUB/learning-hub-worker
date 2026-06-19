"""Flashcard generation task."""

from celery_app import celery_app


@celery_app.task(name="generate_flashcards_task", bind=True, max_retries=3, default_retry_delay=10)
def generate_flashcards_task(self, flashcard_id: str, document_id: str, set_name: str, count: int = 20) -> dict:
    """Generate flashcards from document context and insert into flashcard_items database table."""
    try:
        from src.utils.qdrant_client import search_similar
        from src.utils.embeddings import generate_embedding

        # 1. Retrieve document semantic chunks
        query_vector = generate_embedding(f"flashcards about document {document_id}")
        results = search_similar(query_vector, document_id=document_id, limit=5)
        context = "\n".join([r["payload"]["text"] for r in results]) if results else ""

        # 2. Query AI service for generation
        import httpx
        from src.core.config import settings

        response = httpx.post(
            f"{settings.AI_SERVICE_URL}/study/flashcards/generate",
            headers={"X-Internal-API-Key": settings.INTERNAL_API_KEY},
            json={
                "context": context,
                "set_name": set_name,
                "count": count,
            },
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        items = data.get("items", [])

        # 3. Store in Database
        if items:
            import psycopg2
            import uuid

            conn = psycopg2.connect(settings.DATABASE_URL.replace("+asyncpg", ""))
            cur = conn.cursor()
            
            # Batch SQL insertion for optimal performance under load
            insert_query = "INSERT INTO flashcard_items (id, flashcard_id, front_text, back_text) VALUES (%s, %s, %s, %s)"
            insert_data = [
                (str(uuid.uuid4()), flashcard_id, item.get("front", ""), item.get("back", ""))
                for item in items
            ]
            cur.executemany(insert_query, insert_data)
            conn.commit()
            conn.close()

        return {"status": "completed", "flashcards": items}

    except Exception as exc:
        raise self.retry(exc=exc, countdown=15)
