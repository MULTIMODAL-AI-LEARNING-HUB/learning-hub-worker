"""Document processing task."""

import json
import uuid
from celery_app import celery_app
from src.core.config import settings


@celery_app.task(name="process_document_task", bind=True, max_retries=3)
def process_document_task(self, document_id: str) -> dict:
    """Process an uploaded document: extract text, chunk, embed, store in Qdrant."""
    import psycopg2
    conn = None
    try:
        conn = psycopg2.connect(settings.DATABASE_URL.replace("+asyncpg", ""))
        
        self.update_state(state='PROGRESS', meta={'progress': 5, 'message': 'Starting document processing'})
        _update_status(conn, document_id, "processing")

        doc = _fetch_document(conn, document_id)
        if not doc:
            return {"status": "error", "message": "Document not found"}

        self.update_state(state='PROGRESS', meta={'progress': 10, 'message': 'Downloading file from storage'})
        file_bytes = _download_from_minio(doc["storage_key"])
        if not file_bytes:
            _update_status(conn, document_id, "failed")
            return {"status": "error", "message": "File not found in storage"}

        # Route processing depending on file extension
        ext = doc["file_name"].split(".")[-1].lower() if "." in doc["file_name"] else ""
        pages = []

        if ext == "pdf":
            from src.tasks.pdf_processing import extract_text_from_pdf
            self.update_state(state='PROGRESS', meta={'progress': 20, 'message': 'Extracting text content from PDF'})
            pages = extract_text_from_pdf(file_bytes)
            if not pages:
                _update_status(conn, document_id, "failed")
                return {"status": "error", "message": "No text extracted from PDF"}
        elif ext in {"mp3", "mp4", "webm"}:
            self.update_state(state='PROGRESS', meta={'progress': 20, 'message': 'Transcribing audio/video file'})
            # Mock transcription for video/audio to enable search and chat on uploaded media files
            mock_text = f"This is a mock transcription of the uploaded media file {doc['file_name']}. Content covers main features and architecture of the Multimodal AI Learning Hub platform."
            pages = [{"page_number": 1, "text": mock_text}]
        else:
            _update_status(conn, document_id, "failed")
            return {"status": "error", "message": f"Unsupported file type: {ext}"}

        from src.tasks.pdf_processing import process_pdf_pages

        self.update_state(state='PROGRESS', meta={'progress': 40, 'message': 'Chunking text content'})
        chunks = process_pdf_pages(pages)
        if not chunks:
            _update_status(conn, document_id, "failed")
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
        _update_document_after_processing(conn, document_id, "ready", metadata)
        
        self.update_state(state='SUCCESS', meta={'progress': 100, 'message': 'Document processing completed'})
        return {"status": "completed", "document_id": document_id, "chunks": len(chunks)}

    except Exception as exc:
        if conn:
            _update_status(conn, document_id, "failed")
        raise self.retry(exc=exc, countdown=10)
    finally:
        if conn:
            conn.close()


def _fetch_document(conn, document_id: str) -> dict | None:
    """Fetch document metadata from the database using active DB connection."""
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, file_name, file_url, storage_key, user_id FROM documents WHERE id = %s", (document_id,))
        row = cur.fetchone()
        cur.close()
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


def _update_status(conn, document_id: str, status: str) -> None:
    """Update document status in the database using active DB connection."""
    try:
        cur = conn.cursor()
        cur.execute("UPDATE documents SET status = %s WHERE id = %s", (status, document_id))
        conn.commit()
        cur.close()
    except Exception:
        pass


def _update_document_after_processing(conn, document_id: str, status: str, metadata: dict) -> None:
    """Update document status and metadata after processing using active DB connection."""
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE documents SET status = %s, file_metadata = %s WHERE id = %s",
            (status, json.dumps(metadata), document_id),
        )
        conn.commit()
        cur.close()
    except Exception:
        pass
