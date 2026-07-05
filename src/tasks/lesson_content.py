"""Lesson content processing task - vectorize lesson HTML/text content."""

import uuid
from celery_app import celery_app
from src.core.config import settings


@celery_app.task(name="process_lesson_content_task", bind=True, max_retries=3)
def process_lesson_content_task(self, lesson_id: str, course_id: str | None = None) -> dict:
    """Process lesson content text: strip HTML, chunk, embed, store in Qdrant."""
    import psycopg2
    conn = None
    try:
        conn = psycopg2.connect(settings.DATABASE_URL.replace("+asyncpg", ""))

        self.update_state(state='PROGRESS', meta={'progress': 5, 'message': 'Starting lesson content processing'})

        lesson = _fetch_lesson(conn, lesson_id)
        if not lesson:
            return {"status": "error", "message": "Lesson not found"}

        if not lesson.get("content"):
            return {"status": "skipped", "message": "Lesson has no content"}

        self.update_state(state='PROGRESS', meta={'progress': 15, 'message': 'Processing text content'})

        from src.tasks.pdf_processing import strip_html, chunk_text

        clean_text = strip_html(lesson["content"])
        if not clean_text or len(clean_text.strip()) < 20:
            return {"status": "skipped", "message": "Lesson content too short after cleaning"}

        self.update_state(state='PROGRESS', meta={'progress': 30, 'message': 'Chunking text content'})
        chunks = chunk_text(clean_text, chunk_size=512, overlap=100)
        if not chunks:
            return {"status": "error", "message": "No semantic chunks could be created"}

        course_id_to_use = course_id or lesson.get("course_id")
        self.update_state(state='PROGRESS', meta={'progress': 50, 'message': 'Generating vector embeddings'})

        from src.utils.embeddings import generate_embedding

        qdrant_chunks = []
        total_chunks = len(chunks)
        for idx, text in enumerate(chunks):
            vector = generate_embedding(text)
            qdrant_chunks.append(
                {
                    "id": str(uuid.uuid4()),
                    "vector": vector,
                    "course_id": course_id_to_use,
                    "lesson_id": lesson_id,
                    "chunk_index": idx,
                    "text": text,
                    "source_type": "lesson_content",
                    "user_id": lesson.get("user_id"),
                }
            )
            pct = 50 + int((idx + 1) / total_chunks * 35)
            if idx % 10 == 0 or idx == total_chunks - 1:
                self.update_state(state='PROGRESS', meta={'progress': pct, 'message': f'Embedding chunk {idx+1}/{total_chunks}'})

        from src.utils.qdrant_client import upsert_chunks

        self.update_state(state='PROGRESS', meta={'progress': 90, 'message': 'Upserting vectors to search index'})
        upsert_chunks(qdrant_chunks)

        self.update_state(state='SUCCESS', meta={'progress': 100, 'message': 'Lesson content processing completed'})
        return {"status": "completed", "lesson_id": lesson_id, "course_id": course_id_to_use, "chunks": len(chunks)}

    except Exception as exc:
        raise self.retry(exc=exc, countdown=10)
    finally:
        if conn:
            conn.close()


def _fetch_lesson(conn, lesson_id: str) -> dict | None:
    """Fetch lesson with content and course info from database."""
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT l.id, l.title, l.content, l.section_id, s.course_id, c.lecturer_id
            FROM lessons l
            JOIN sections s ON l.section_id = s.id
            JOIN courses c ON s.course_id = c.id
            WHERE l.id = %s
        """, (lesson_id,))
        row = cur.fetchone()
        cur.close()
        if row:
            return {
                "id": str(row[0]),
                "title": row[1],
                "content": row[2],
                "section_id": str(row[3]),
                "course_id": str(row[4]),
                "user_id": str(row[5]),
            }
        return None
    except Exception:
        return None


def _update_lesson_indexed(conn, lesson_id: str, indexed: bool) -> None:
    """Mark lesson as having been indexed in Qdrant (no DB column yet - placeholder)."""
    pass