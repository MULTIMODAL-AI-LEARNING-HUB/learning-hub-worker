"""Document processing task."""

import json
import uuid
from celery_app import celery_app
from src.core.config import settings


@celery_app.task(name="process_document_task", bind=True, max_retries=3)
def process_document_task(self, document_id: str) -> dict:
    """Process an uploaded document: extract text, chunk, embed, store in Qdrant."""
    try:
        self.update_state(state='PROGRESS', meta={'progress': 5, 'message': 'Starting document processing'})
        _update_status(document_id, "processing")

        doc = _fetch_document(document_id)
        if not doc:
            return {"status": "error", "message": "Document not found"}

        self.update_state(state='PROGRESS', meta={'progress': 10, 'message': 'Downloading file from storage'})
        pdf_bytes = _download_from_minio(doc["storage_key"])
        if not pdf_bytes:
            _update_status(document_id, "failed")
            return {"status": "error", "message": "File not found in storage"}

        from src.tasks.pdf_processing import extract_text_from_pdf, process_pdf_pages

        self.update_state(state='PROGRESS', meta={'progress': 20, 'message': 'Extracting text content from PDF'})
        pages = extract_text_from_pdf(pdf_bytes)
        if not pages:
            _update_status(document_id, "failed")
            return {"status": "error", "message": "No text extracted from PDF"}

        self.update_state(state='PROGRESS', meta={'progress': 40, 'message': 'Chunking text content'})
        chunks = process_pdf_pages(pages)
        if not chunks:
            _update_status(document_id, "failed")
            return {"status": "error", "message": "No semantic chunks could be created"}

        from src.utils.embeddings import generate_embedding

        self.update_state(state='PROGRESS', meta={'progress': 50, 'message': 'Generating vector embeddings'})
        qdrant_chunks = []
        total_chunks = len(chunks)
        for idx, chunk in enumerate(chunks):
            # Generate real sentence-transformers embeddings
            vector = generate_embedding(chunk["text"])
            qdrant_chunks.append(
                {
                    "id": str(uuid.uuid4()),
                    "vector": vector,
                    "document_id": document_id,
                    "user_id": doc.get("user_id"),
                    "chunk_index": chunk["chunk_index"],
                    "text": chunk["text"],
                    "page_number": chunk.get("page_number"),
                }
            )
            # Update progress dynamically between 50% and 85%
            pct = 50 + int((idx + 1) / total_chunks * 35)
            if idx % 10 == 0 or idx == total_chunks - 1:
                self.update_state(state='PROGRESS', meta={'progress': pct, 'message': f'Embedding chunk {idx+1}/{total_chunks}'})

        from src.utils.qdrant_client import upsert_chunks

        self.update_state(state='PROGRESS', meta={'progress': 90, 'message': 'Upserting vectors to search index'})
        upsert_chunks(qdrant_chunks)

        metadata = {
            "page_count": len(pages),
            "chunk_count": len(chunks),
        }
        _update_document_after_processing(document_id, "ready", metadata)
        
        self.update_state(state='SUCCESS', meta={'progress': 100, 'message': 'Document processing completed'})
        return {"status": "completed", "document_id": document_id, "chunks": len(chunks)}

    except Exception as exc:
        _update_status(document_id, "failed")
        raise self.retry(exc=exc, countdown=10)


def _fetch_document(document_id: str) -> dict | None:
    """Fetch document metadata from the database using sync DB connection."""
    try:
        import psycopg2

        conn = psycopg2.connect(settings.DATABASE_URL.replace("+asyncpg", ""))
        cur = conn.cursor()
        cur.execute("SELECT id, file_name, file_url, storage_key, user_id FROM documents WHERE id = %s", (document_id,))
        row = cur.fetchone()
        conn.close()
        if row:
            return {"id": str(row[0]), "file_name": row[1], "file_url": row[2], "storage_key": row[3], "user_id": str(row[4])}
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
