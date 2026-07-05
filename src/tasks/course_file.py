"""Course context file processing task - process files from MinIO with course/lesson metadata."""

import uuid
from celery_app import celery_app
from src.core.config import settings


@celery_app.task(name="process_course_file_task", bind=True, max_retries=3)
def process_course_file_task(
    self,
    storage_key: str,
    course_id: str,
    lesson_id: str | None = None,
    material_id: str | None = None,
    source_type: str = "course_material",
    file_name: str | None = None,
) -> dict:
    """Process a file from MinIO with course context metadata.

    Args:
        storage_key: MinIO object storage key
        course_id: Course UUID
        lesson_id: Optional lesson UUID for lesson attachments
        material_id: Optional material UUID for course materials
        source_type: "course_material" | "lesson_attachment"
        file_name: Original filename for extension detection
    """
    import psycopg2
    conn = None
    try:
        conn = psycopg2.connect(settings.DATABASE_URL.replace("+asyncpg", ""))

        self.update_state(state='PROGRESS', meta={'progress': 5, 'message': 'Starting file processing'})

        if not file_name:
            file_name = storage_key.split("/")[-1] if "/" in storage_key else "file.pdf"

        self.update_state(state='PROGRESS', meta={'progress': 10, 'message': 'Downloading file from storage'})
        file_bytes = _download_from_minio(storage_key)
        if not file_bytes:
            return {"status": "error", "message": "File not found in storage"}

        ext = file_name.split(".")[-1].lower() if "." in file_name else ""
        pages = []

        if ext == "pdf":
            from src.tasks.pdf_processing import extract_text_from_pdf, process_pdf_pages
            self.update_state(state='PROGRESS', meta={'progress': 20, 'message': 'Extracting text content from PDF'})
            pages = extract_text_from_pdf(file_bytes)
            if not pages:
                return {"status": "error", "message": "No text extracted from PDF"}
        elif ext in {"mp3", "mp4", "webm"}:
            self.update_state(state='PROGRESS', meta={'progress': 20, 'message': 'Processing media file'})
            mock_text = f"Content from media file {file_name}."
            pages = [{"page_number": 1, "text": mock_text}]
        else:
            return {"status": "error", "message": f"Unsupported file type: {ext}"}

        from src.tasks.pdf_processing import process_pdf_pages

        self.update_state(state='PROGRESS', meta={'progress': 40, 'message': 'Chunking text content'})
        chunks = process_pdf_pages(pages)
        if not chunks:
            return {"status": "error", "message": "No semantic chunks could be created"}

        self.update_state(state='PROGRESS', meta={'progress': 50, 'message': 'Generating vector embeddings'})

        from src.utils.embeddings import generate_embedding

        qdrant_chunks = []
        total_chunks = len(chunks)
        for idx, chunk in enumerate(chunks):
            vector = generate_embedding(chunk["text"])
            qdrant_chunks.append(
                {
                    "id": str(uuid.uuid4()),
                    "vector": vector,
                    "course_id": course_id,
                    "lesson_id": lesson_id,
                    "material_id": material_id,
                    "chunk_index": chunk["chunk_index"],
                    "text": chunk["text"],
                    "page_number": chunk.get("page_number"),
                    "source_type": source_type,
                }
            )
            pct = 50 + int((idx + 1) / total_chunks * 35)
            if idx % 10 == 0 or idx == total_chunks - 1:
                self.update_state(state='PROGRESS', meta={'progress': pct, 'message': f'Embedding chunk {idx+1}/{total_chunks}'})

        from src.utils.qdrant_client import upsert_chunks

        self.update_state(state='PROGRESS', meta={'progress': 90, 'message': 'Upserting vectors to search index'})
        upsert_chunks(qdrant_chunks)

        self.update_state(state='SUCCESS', meta={'progress': 100, 'message': 'File processing completed'})
        return {
            "status": "completed",
            "storage_key": storage_key,
            "course_id": course_id,
            "lesson_id": lesson_id,
            "material_id": material_id,
            "source_type": source_type,
            "chunks": len(chunks)
        }

    except Exception as exc:
        raise self.retry(exc=exc, countdown=10)
    finally:
        if conn:
            conn.close()


def _download_from_minio(storage_key: str) -> bytes | None:
    """Download file bytes from MinIO by storage key."""
    try:
        from src.utils.minio_client import download_file
        resp = download_file(storage_key)
        return resp.read()
    except Exception:
        return None