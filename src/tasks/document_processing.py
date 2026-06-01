"""Document processing task."""

import json
import uuid

from celery_app import celery_app
from src.core.config import settings


@celery_app.task(name="process_document_task", bind=True, max_retries=3)
def process_document_task(self, document_id: str) -> dict:
    """Process an uploaded document: extract text, chunk, embed, store in Qdrant."""
    try:
        _update_status(document_id, "processing")

        doc = _fetch_document(document_id)
        if not doc:
            return {"status": "error", "message": "Document not found"}

        pdf_bytes = _download_from_minio(document_id)
        if not pdf_bytes:
            _update_status(document_id, "failed")
            return {"status": "error", "message": "File not found in storage"}

        from src.tasks.pdf_processing import extract_text_from_pdf, process_pdf_pages

        pages = extract_text_from_pdf(pdf_bytes)
        if not pages:
            _update_status(document_id, "failed")
            return {"status": "error", "message": "No text extracted from PDF"}

        chunks = process_pdf_pages(pages)

        from src.utils.embeddings import generate_embedding

        qdrant_chunks = []
        for chunk in chunks:
            vector = generate_embedding(chunk["text"])
            qdrant_chunks.append(
                {
                    "id": str(uuid.uuid4()),
                    "vector": vector,
                    "document_id": document_id,
                    "chunk_index": chunk["chunk_index"],
                    "text": chunk["text"],
                    "page_number": chunk.get("page_number"),
                }
            )

        from src.utils.qdrant_client import upsert_chunks

        upsert_chunks(qdrant_chunks)

        metadata = {
            "page_count": len(pages),
            "chunk_count": len(chunks),
        }
        _update_document_after_processing(document_id, "ready", metadata)

        return {"status": "completed", "document_id": document_id, "chunks": len(chunks)}

    except Exception as exc:
        _update_status(document_id, "failed")
        self.retry(exc=exc, countdown=60)


def _fetch_document(document_id: str) -> dict | None:
    """Fetch document metadata from the database using sync DB connection."""
    try:
        import psycopg2

        conn = psycopg2.connect(settings.DATABASE_URL.replace("+asyncpg", ""))
        cur = conn.cursor()
        cur.execute("SELECT id, file_name, file_url, storage_key FROM documents WHERE id = %s", (document_id,))
        row = cur.fetchone()
        conn.close()
        if row:
            return {"id": str(row[0]), "file_name": row[1], "file_url": row[2], "storage_key": row[3]}
        return None
    except Exception:
        return None


def _download_from_minio(document_id: str) -> bytes | None:
    """Download file bytes from MinIO by document ID."""
    try:
        from src.utils.minio_client import download_file

        resp = download_file(document_id)
        return resp.read()
    except Exception:
        return None


def _update_status(document_id: str, status: str) -> None:
    """Update document status in the database."""
    try:
        import psycopg2

        conn = psycopg2.connect(settings.DATABASE_URL.replace("+asyncpg", ""))
        cur = conn.cursor()
        cur.execute("UPDATE documents SET status = %s WHERE id = %s", (status, document_id))
        conn.commit()
        conn.close()
    except Exception:
        pass


def _update_document_after_processing(document_id: str, status: str, metadata: dict) -> None:
    """Update document status and metadata after processing."""
    try:
        import psycopg2

        conn = psycopg2.connect(settings.DATABASE_URL.replace("+asyncpg", ""))
        cur = conn.cursor()
        cur.execute(
            "UPDATE documents SET status = %s, file_metadata = %s WHERE id = %s",
            (status, json.dumps(metadata), document_id),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass
