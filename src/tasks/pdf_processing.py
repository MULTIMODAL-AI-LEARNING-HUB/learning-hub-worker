"""PDF text extraction and enterprise-grade recursive semantic chunking.

Extraction chain (2026-09 upgrade):
  1. PyMuPDF (fitz) primary — best text-layer fidelity for complex layouts,
     tables, and odd encodings; also renders page images for OCR fallback.
  2. pypdf fills pages PyMuPDF missed.
  3. pdfplumber fills any still-empty pages (tables/odd encodings).
  4. OCR fallback (PyMuPDF pixmap + Tesseract, vie+eng) for scanned /
     image-only pages — gracefully skipped when deps are absent.
"""

import io
import logging
import re

logger = logging.getLogger("worker.pdf_processing")

# all-MiniLM-L6-v2 supports max 256 tokens (~1000-1200 chars for EN,
# ~600-800 chars for VI due to subword fragmentation). Keep chunks well
# below the limit so embeddings never get silently truncated.
DEFAULT_CHUNK_SIZE = 800
DEFAULT_CHUNK_OVERLAP = 150

# Logical academic page (~350-400 words, ~1 A4 page) for office/txt docs
# that have no native page structure.
CHARS_PER_LOGICAL_PAGE = 2000

# Separators in priority order: paragraph -> line -> sentence -> clause -> word -> char
DEFAULT_SEPARATORS = ["\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " ", ""]


def strip_html(text: str) -> str:
    """Remove HTML tags from text, keeping readable content."""
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def clean_text(text: str | None) -> str:
    """Deep-clean extracted text: NUL bytes, repeated headers/footers, page artifacts."""
    if not text:
        return ""
    text = text.replace("\x00", " ")
    # Remove common page artifacts: long dash runs, page number lines
    text = re.sub(r'[─\-_=]{4,}', ' ', text)
    text = re.sub(r'[ \t]+', ' ', text)
    # Collapse 3+ newlines to paragraph break
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Remove lines that are pure page numbers like "  12  " or "Page 12 of 50"
    lines = []
    for line in text.split('\n'):
        s = line.strip()
        if not s:
            continue
        if re.fullmatch(r'(trang\s+\d+(\s*/\s*\d+)?|page\s+\d+(\s+of\s+\d+)?|\d+)', s, re.IGNORECASE):
            continue
        lines.append(line)
    text = '\n'.join(lines).strip()
    if len(re.sub(r'\s+', '', text)) < 3:
        return ""
    return text


def _clean_page_text(text: str | None) -> str:
    """Normalize extracted page text; drop pages without real content."""
    return clean_text(text)


def _extract_with_pymupdf(pdf_bytes: bytes) -> list[str]:
    """Per-page text via PyMuPDF (fitz) — primary engine.

    Best fidelity for complex layouts, embedded fonts and tables.
    Returns [] when PyMuPDF is not installed so callers fall through.
    """
    try:
        import fitz
    except ImportError:
        return []
    texts: list[str] = []
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            if getattr(doc, "needs_pass", False):
                try:
                    doc.authenticate("")
                except Exception:
                    pass
            for page in doc:
                try:
                    raw = page.get_text("text") or ""
                    texts.append(_clean_page_text(raw))
                except Exception:
                    texts.append("")
    except Exception as exc:
        logger.warning("pymupdf extraction failed: %s", exc)
        return []
    return texts


def _extract_with_ocr(pdf_bytes: bytes, page_numbers: list[int]) -> dict[int, str]:
    """OCR fallback for scanned/image-only pages via PyMuPDF + Tesseract.

    Returns {page_number (1-based): text}. Empty dict when deps are absent
    or OCR yields nothing — callers must handle gracefully.
    """
    if not page_numbers:
        return {}
    try:
        import fitz
    except ImportError:
        return {}
    try:
        from PIL import Image
    except ImportError:
        return {}
    try:
        import pytesseract
    except ImportError:
        logger.info("pytesseract not installed — skipping OCR fallback")
        return {}
    results: dict[int, str] = {}
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            for pn in page_numbers:
                idx = pn - 1
                if idx < 0 or idx >= len(doc):
                    continue
                try:
                    page = doc[idx]
                    pix = page.get_pixmap(dpi=200)
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    raw = pytesseract.image_to_string(img, lang="vie+eng")
                    cleaned = _clean_page_text(raw)
                    if cleaned:
                        results[pn] = cleaned
                except Exception as exc:
                    logger.warning("OCR failed on page %s: %s", pn, exc)
    except Exception as exc:
        logger.warning("OCR fallback failed: %s", exc)
    return results


def _extract_with_pypdf(pdf_bytes: bytes) -> list[str]:
    """Per-page text via pypdf. Returns list indexed by page ('' when empty)."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return []
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
                    raw = page.extract_text() or ""
                    # pdfplumber preserves table pipes; normalize spacing
                    raw = re.sub(r'[ \t]+\|?[ \t]+', ' ', raw)
                    texts.append(_clean_page_text(raw))
                except Exception:
                    texts.append("")
    except Exception as exc:
        logger.warning("pdfplumber fallback failed: %s", exc)
        return []
    return texts


def extract_text_from_pdf(pdf_bytes: bytes) -> list[dict]:
    """Extract text from PDF, returning list of {page_number, text, engine}.

    Chain: PyMuPDF primary -> pypdf fills gaps -> pdfplumber fills the rest
    -> OCR fallback (vie+eng) for still-empty pages. engine records which
    layer produced each page so document metadata can report extraction
    quality (text_native vs ocr vs empty counts).
    """
    if not pdf_bytes:
        return []
    primary: list[str] = []
    try:
        primary = _extract_with_pymupdf(pdf_bytes)
    except Exception as exc:
        logger.warning("pymupdf extraction failed: %s", exc)
        primary = []
    if not primary:
        try:
            primary = _extract_with_pypdf(pdf_bytes)
        except Exception as exc:
            logger.warning("pypdf extraction failed: %s", exc)
            return []
    if not primary:
        return []
    engines = ["pymupdf" if t else "" for t in primary]
    if any(not t for t in primary):
        try:
            second = _extract_with_pypdf(pdf_bytes)
        except Exception:
            second = []
        if second and len(second) == len(primary):
            for i, (p, s) in enumerate(zip(primary, second)):
                if not p and s:
                    primary[i] = s
                    engines[i] = "pypdf"
    if any(not t for t in primary):
        fallback = _extract_with_pdfplumber(pdf_bytes)
        if fallback and len(fallback) == len(primary):
            for i, (p, f) in enumerate(zip(primary, fallback)):
                if not p and f:
                    primary[i] = f
                    engines[i] = "pdfplumber"
    if any(not t for t in primary):
        missing = [i + 1 for i, t in enumerate(primary) if not t]
        ocr = _extract_with_ocr(pdf_bytes, missing)
        for pn, text in ocr.items():
            primary[pn - 1] = text
            engines[pn - 1] = "ocr"
    pages = []
    for i, text in enumerate(primary):
        if text:
            pages.append({"page_number": i + 1, "text": text, "engine": engines[i] or "unknown"})
    return pages


def extraction_metrics(pages: list[dict], total_pages: int) -> dict:
    """Summarize extraction quality for document metadata."""
    by_engine: dict[str, int] = {}
    for p in pages:
        eng = p.get("engine", "unknown")
        by_engine[eng] = by_engine.get(eng, 0) + 1
    covered = len(pages)
    return {
        "total_pages": total_pages or covered,
        "pages_with_text": covered,
        "empty_pages": max(0, (total_pages or covered) - covered),
        "engines": by_engine,
        "ocr_pages": by_engine.get("ocr", 0),
    }


def paginate_long_text(text: str, chars_per_page: int = CHARS_PER_LOGICAL_PAGE) -> list[dict]:
    """Split a long plain text (txt/docx) into logical academic pages.

    Breaks on paragraph boundaries so citations can reference page numbers
    instead of everything being 'page 1'. Returns [{page_number, text}].
    """
    text = clean_text(text)
    if not text:
        return []
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
    if not paragraphs:
        return [{"page_number": 1, "text": text}]
    pages: list[dict] = []
    current: list[str] = []
    current_len = 0
    page_no = 1
    for para in paragraphs:
        # A single giant paragraph gets hard-split to avoid overflow
        while len(para) > chars_per_page:
            if current:
                pages.append({"page_number": page_no, "text": "\n\n".join(current)})
                page_no += 1
                current = []
                current_len = 0
            pages.append({"page_number": page_no, "text": para[:chars_per_page]})
            page_no += 1
            para = para[chars_per_page:]
        if current_len + len(para) + 2 > chars_per_page and current:
            pages.append({"page_number": page_no, "text": "\n\n".join(current)})
            page_no += 1
            current = [para]
            current_len = len(para)
        else:
            current.append(para)
            current_len += len(para) + 2
    if current:
        pages.append({"page_number": page_no, "text": "\n\n".join(current)})
    return pages


def recursive_split_text(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
    separators: list[str] | None = None,
) -> list[str]:
    """Recursively split text on natural boundaries (paragraph/sentence/word).

    Unlike fixed word-window chunking, this never cuts a sentence in half
    when a coarser boundary fits, keeping each chunk semantically coherent
    and safely below the embedding model's 256-token limit.
    """
    if not text or not text.strip():
        return []
    if separators is None:
        separators = DEFAULT_SEPARATORS
    text = text.strip()
    if len(text) <= chunk_size:
        return [text]

    sep = ""
    next_seps: list[str] = []
    for i, s in enumerate(separators):
        if s == "" or s in text:
            sep = s
            next_seps = separators[i + 1:]
            break

    splits = list(text) if sep == "" else text.split(sep)

    chunks: list[str] = []
    current_parts: list[str] = []
    current_len = 0

    def _flush() -> None:
        nonlocal current_parts, current_len
        if current_parts:
            piece = (sep.join(current_parts)).strip() if sep else "".join(current_parts).strip()
            if piece and (not chunks or piece != chunks[-1]):
                chunks.append(piece)
            current_parts = []
            current_len = 0

    def _overlap_seed(last_chunk: str) -> tuple[list[str], int]:
        if overlap <= 0 or not last_chunk:
            return [], 0
        seed = last_chunk[-overlap:]
        # snap to word boundary
        space_idx = seed.find(" ")
        if 0 <= space_idx < len(seed) - 1:
            seed = seed[space_idx + 1:]
        seed = seed.strip()
        if not seed:
            return [], 0
        return [seed], len(seed) + len(sep)

    for part in splits:
        if not part or (sep != "" and not part.strip()):
            continue
        # Recurse into oversized parts with finer separators
        if sep != "" and len(part) > chunk_size and next_seps:
            sub_chunks = recursive_split_text(part, chunk_size, overlap, next_seps)
            for sub in sub_chunks:
                add_len = len(sub) + (len(sep) if current_parts else 0)
                if current_len + add_len > chunk_size and current_parts:
                    _flush()
                    if chunks:
                        ov_parts, ov_len = _overlap_seed(chunks[-1])
                        current_parts = ov_parts
                        current_len = ov_len
                current_parts.append(sub)
                current_len += len(sub) + (len(sep) if len(current_parts) > 1 else 0)
            continue
        if sep == "" and len(part) > chunk_size:
            # pure char fallback: hard slice
            for j in range(0, len(part), chunk_size - overlap):
                piece = part[j:j + chunk_size]
                if piece.strip():
                    chunks.append(piece.strip())
            continue
        add_len = len(part) + (len(sep) if current_parts else 0)
        if current_len + add_len > chunk_size and current_parts:
            _flush()
            if chunks:
                ov_parts, ov_len = _overlap_seed(chunks[-1])
                current_parts = ov_parts
                current_len = ov_len
        current_parts.append(part)
        # recompute length cheaply
        current_len = len(sep.join(current_parts)) if sep else len("".join(current_parts))
    _flush()
    return [c for c in chunks if c.strip()]


# Backward-compat alias: old signature used word counts (512 words).
# New implementation treats oversized legacy values as chars but clamps
# to the safe embedding window.
def chunk_text(text: str, chunk_size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping semantic chunks (char-based)."""
    if chunk_size > 1200:
        # Legacy callers passed word-count 512 (≈3000+ chars) — clamp to safe window
        chunk_size = DEFAULT_CHUNK_SIZE
    if overlap >= chunk_size:
        overlap = DEFAULT_CHUNK_OVERLAP
    return recursive_split_text(text, chunk_size=chunk_size, overlap=overlap)


def process_pdf_pages(
    pages: list[dict],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[dict]:
    """Process pages into semantic chunks with metadata."""
    if chunk_size > 1200:
        chunk_size = DEFAULT_CHUNK_SIZE
    if overlap >= chunk_size:
        overlap = DEFAULT_CHUNK_OVERLAP
    all_chunks = []
    chunk_index = 0
    for page in pages:
        page_chunks = recursive_split_text(page.get("text", ""), chunk_size, overlap)
        for text in page_chunks:
            all_chunks.append(
                {
                    "chunk_index": chunk_index,
                    "page_number": page.get("page_number", 1),
                    "text": text,
                    "char_count": len(text),
                }
            )
            chunk_index += 1
    return all_chunks
