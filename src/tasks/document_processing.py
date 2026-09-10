"""Document processing task."""

import json
import logging
import uuid
from celery_app import celery_app
from src.core.config import settings

logger = logging.getLogger("worker.document_processing")

# NOTE: bang documents dung cot DB ten "metadata" (model API anh xa
# file_metadata -> "metadata"). Raw SQL bat buoc dung dung ten cot DB,
# neu dung "file_metadata" se loi column khong ton tai va document ket
# processing mai mai.


@celery_app.task(name="process_document_task", bind=True, max_retries=3)
def process_document_task(self, document_id: str) -> dict:
    """Process an uploaded document: extract text, chunk, embed, store in Qdrant."""
    try:
        uuid.UUID(document_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Invalid document UUID") from exc

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
        file_bytes, dl_error = _download_from_minio(doc["storage_key"])
        if not file_bytes:
            _update_status(conn, document_id, "failed", error=dl_error or "File not found in storage")
            return {"status": "error", "message": dl_error or "File not found in storage"}

        # Route processing depending on file extension
        ext = doc["file_name"].split(".")[-1].lower() if "." in doc["file_name"] else ""
        pages = []

        if ext == "pdf":
            from src.tasks.pdf_processing import extract_text_from_pdf
            self.update_state(state='PROGRESS', meta={'progress': 20, 'message': 'Extracting text content from PDF'})
            pages = extract_text_from_pdf(file_bytes)
            if not pages:
                msg = (
                    "No readable text found in this PDF. "
                    "It may be a scanned/image-only file with no text layer — "
                    "please upload a text-based PDF, or a TXT/DOCX version instead."
                )
                _update_status(conn, document_id, "failed", error=msg)
                return {"status": "error", "message": msg}
        elif ext in {"mp3", "mp4", "webm", "wav"}:
            self.update_state(state='PROGRESS', meta={'progress': 20, 'message': 'Transcribing audio/video file'})
            from src.tasks.transcription import transcribe_media
            pages = transcribe_media(file_bytes, ext, file_name=doc.get("file_name", ""))
        elif ext in {"txt", "doc", "docx"}:
            self.update_state(state='PROGRESS', meta={'progress': 20, 'message': 'Extracting text from office document'})
            from src.tasks.office_text import extract_text_from_office_file
            from src.tasks.pdf_processing import paginate_long_text
            text = extract_text_from_office_file(file_bytes, ext)
            if not text:
                _update_status(conn, document_id, "failed", error=f"No text extracted from {ext.upper()} file")
                return {"status": "error", "message": f"No text extracted from {ext.upper()} file"}
            # Paginate long office docs into logical academic pages so
            # citations reference real page numbers instead of "page 1".
            pages = paginate_long_text(text)
            if not pages:
                _update_status(conn, document_id, "failed", error=f"No text extracted from {ext.upper()} file")
                return {"status": "error", "message": f"No text extracted from {ext.upper()} file"}
        else:
            _update_status(conn, document_id, "failed", error=f"Unsupported file type: {ext}")
            return {"status": "error", "message": f"Unsupported file type: {ext}"}

        from src.tasks.pdf_processing import process_pdf_pages

        self.update_state(state='PROGRESS', meta={'progress': 40, 'message': 'Chunking text content'})
        chunks = process_pdf_pages(pages)
        if not chunks:
            _update_status(conn, document_id, "failed", error="No semantic chunks could be created")
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
        try:
            upsert_chunks(qdrant_chunks)
        except Exception as exc:
            logger.warning("Qdrant upsert failed for %s: %s", document_id, exc)
            _update_status(conn, document_id, "failed", error=f"Vector index upsert failed: {exc}")
            raise

        avg_chars = round(sum(len(c.get("text", "")) for c in chunks) / len(chunks)) if chunks else 0
        try:
            from src.tasks.pdf_processing import extraction_metrics
            total_pg = len(pages)
            try:
                from pypdf import PdfReader as _PR
                import io as _io
                total_pg = len(_PR(_io.BytesIO(file_bytes)).pages) or len(pages)
            except Exception:
                pass
            ext_metrics = extraction_metrics(pages, total_pg) if ext == "pdf" else {}
        except Exception:
            ext_metrics = {}
        metadata = {
            "page_count": len(pages),
            "chunk_count": len(chunks),
            "chunking": "recursive_semantic_v2",
            "avg_chunk_chars": avg_chars,
            "extraction": ext_metrics,
        }
        _update_document_after_processing(conn, document_id, "ready", metadata)

        self.update_state(state='SUCCESS', meta={'progress': 100, 'message': 'Document processing completed'})
        return {"status": "completed", "document_id": document_id, "chunks": len(chunks)}

    except Exception as exc:
        if conn:
            _update_status(conn, document_id, "failed", error=f"{type(exc).__name__}: {exc}")
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
    except Exception as exc:
        logger.warning("Failed to fetch document %s: %s", document_id, exc)
        return None


def _download_from_minio(storage_key: str) -> tuple[bytes | None, str | None]:
    """Download file bytes from MinIO/R2 by storage key.

    Returns (bytes, None) on success or (None, error_message) on failure
    so the caller can persist the reason instead of failing silently.
    """
    try:
        from src.utils.minio_client import download_file

        resp = download_file(storage_key)
        try:
            return resp.read(), None
        finally:
            try:
                resp.close()
            except Exception:
                pass
    except Exception as exc:
        logger.warning("Download failed for storage key %s: %s", storage_key, exc)
        return None, f"{type(exc).__name__}: {exc}"


def _update_status(conn, document_id: str, status: str, error: str | None = None) -> None:
    """Update document status, persisting the failure reason into metadata when given."""
    try:
        cur = conn.cursor()
        if error:
            cur.execute(
                'UPDATE documents SET status = %s, metadata = %s::jsonb WHERE id = %s',
                (status, json.dumps({"error": str(error)[:2000]}), document_id),
            )
        else:
            cur.execute("UPDATE documents SET status = %s WHERE id = %s", (status, document_id))
        conn.commit()
        cur.close()
    except Exception as exc:
        logger.warning("Failed to update status for %s: %s", document_id, exc)
        try:
            conn.rollback()
        except Exception:
            pass


def _update_document_after_processing(conn, document_id: str, status: str, metadata: dict) -> None:
    """Update document status and metadata after processing using active DB connection."""
    try:
        from psycopg2.extras import Json

        cur = conn.cursor()
        cur.execute(
            'UPDATE documents SET status = %s, metadata = %s WHERE id = %s',
            (status, Json(metadata), document_id),
        )
        conn.commit()
        cur.close()
    except Exception as exc:
        logger.warning("Failed to finalize document %s: %s", document_id, exc)
        try:
            conn.rollback()
        except Exception:
            pass
        raise
