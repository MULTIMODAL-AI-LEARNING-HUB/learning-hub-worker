"""Quiz generation task for course/lesson content using Qdrant vector search."""

from celery_app import celery_app
from src.core.config import settings


@celery_app.task(name="generate_quiz_by_course_task", bind=True, max_retries=3, default_retry_delay=10)
def generate_quiz_by_course_task(
    self,
    course_id: str,
    lesson_ids: list[str] | None = None,
    quiz_type: str = "quick",
    question_count: int = 10
) -> dict:
    """Generate quiz questions from course or lesson content via Qdrant search.

    Args:
        course_id: Course UUID to filter content from
        lesson_ids: Optional list of specific lesson UUIDs to focus on
        quiz_type: "quick" (5 questions) or "detailed" (10-20 questions)
        question_count: Number of questions to generate (default 10)
    """
    try:
        from src.utils.qdrant_client import search_similar
        from src.utils.embeddings import generate_embedding

        query_text = "quiz questions about this course content lesson material"
        query_vector = generate_embedding(query_text)

        if lesson_ids:
            results = search_similar(
                query_vector,
                course_id=course_id,
                material_ids=lesson_ids,
                limit=15
            )
        else:
            results = search_similar(
                query_vector,
                course_id=course_id,
                limit=15
            )

        context_chunks = [r["payload"]["text"] for r in results if r.get("payload", {}).get("text")]
        context = "\n\n".join(context_chunks) if context_chunks else ""

        import httpx
        response = httpx.post(
            f"{settings.AI_SERVICE_URL}/study/quiz/generate",
            headers={"X-Internal-API-Key": settings.INTERNAL_API_KEY},
            json={
                "context": context[:3000] if context else "Generate general quiz questions about the course.",
                "quiz_type": quiz_type,
                "question_count": question_count,
            },
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()

        return {
            "status": "completed",
            "course_id": course_id,
            "lesson_ids": lesson_ids or [],
            "questions": data.get("questions", []),
            "source_chunks": len(results)
        }

    except Exception as exc:
        raise self.retry(exc=exc, countdown=15)