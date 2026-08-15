"""PDF text extraction and chunking."""

import io
import re
from PyPDF2 import PdfReader


def strip_html(text: str) -> str:
    """Remove HTML tags from text, keeping readable content."""
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def extract_text_from_pdf(pdf_bytes: bytes) -> list[dict]:
    """Extract text from PDF, returning list of {page_number, text}."""
    if not pdf_bytes:
        return []
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text and text.strip():
                pages.append({"page_number": i + 1, "text": text.strip()})
        return pages
    except Exception:
        return []



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
