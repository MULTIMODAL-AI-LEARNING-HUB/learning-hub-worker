"""PDF text extraction and chunking."""

import io
import logging
import re
from pypdf import PdfReader

logger = logging.getLogger("worker.pdf_processing")


def strip_html(text: str) -> str:
    """Remove HTML tags from text, keeping readable content."""
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _clean_page_text(text: str | None) -> str:
    """Normalize extracted page text; drop pages without real content."""
    if not text:
        return ""
    # pypdf sometimes returns NUL bytes / excessive whitespace for broken encodings
    text = text.replace("\x00", " ")
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()
    # A page with only a couple of stray glyphs is not usable content
    if len(re.sub(r'\s+', '', text)) < 3:
        return ""
    return text


def _extract_with_pypdf(pdf_bytes: bytes) -> list[str]:
    """Per-page text via pypdf. Returns list indexed by page ('' when empty)."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    try:
        if getattr(reader, "is_encrypted", False):
            try:
                reader.decrypt("")
            except Exception:
                pass
    except Exception:
        pass
    texts: list[str] = []
    for page in reader.pages:
        try:
            texts.append(_clean_page_text(page.extract_text() or ""))
        except Exception:
            texts.append("")
    return texts


def _extract_with_pdfplumber(pdf_bytes: bytes) -> list[str]:
    """Per-page text via pdfplumber (better for tables/odd encodings)."""
    try:
        import pdfplumber
    except ImportError:
        return []
    texts: list[str] = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                try:
                    texts.append(_clean_page_text(page.extract_text() or ""))
                except Exception:
                    texts.append("")
    except Exception as exc:
        logger.warning("pdfplumber fallback failed: %s", exc)
        return []
    return texts


def extract_text_from_pdf(pdf_bytes: bytes) -> list[dict]:
    """Extract text from PDF, returning list of {page_number, text}.

    Strategy: pypdf first, then pdfplumber fills in pages pypdf missed.
    Returns [] only when no page yields usable text (e.g. scanned/image-only
    PDF with no text layer) — the caller turns that into an actionable error.
    """
    if not pdf_bytes:
        return []
    try:
        primary = _extract_with_pypdf(pdf_bytes)
    except Exception as exc:
        logger.warning("pypdf extraction failed: %s", exc)
        return []
    if not primary:
        return []
    if any(not t for t in primary):
        fallback = _extract_with_pdfplumber(pdf_bytes)
        if fallback and len(fallback) == len(primary):
            primary = [p or f for p, f in zip(primary, fallback)]
    pages = []
    for i, text in enumerate(primary):
        if text:
            pages.append({"page_number": i + 1, "text": text})
    return pages



def chunk_text(text: str, chunk_size: int = 512, overlap: int = 100) -> list[str]:
    """Split text into overlapping chunks."""
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunk = " ".join(words[start:end])
        if chunk.strip():
            chunks.append(chunk)
        start = end - overlap
    return chunks


def process_pdf_pages(pages: list[dict], chunk_size: int = 512, overlap: int = 100) -> list[dict]:
    """Process PDF pages into chunks with metadata."""
    all_chunks = []
    chunk_index = 0
    for page in pages:
        page_chunks = chunk_text(page["text"], chunk_size, overlap)
        for text in page_chunks:
            all_chunks.append(
                {
                    "chunk_index": chunk_index,
                    "page_number": page["page_number"],
                    "text": text,
                }
            )
            chunk_index += 1
    return all_chunks
