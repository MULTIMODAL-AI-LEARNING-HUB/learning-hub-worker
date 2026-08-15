import pytest
from unittest.mock import patch, MagicMock
from src.tasks.pdf_processing import process_pdf_pages, extract_text_from_pdf

def test_process_pdf_pages_chunking():
    pages = [
        {"page_number": 1, "text": "This is a long sentence for testing chunking behavior." * 10},
        {"page_number": 2, "text": "Second page content for verifying page number propagation." * 5}
    ]

    chunks = process_pdf_pages(pages)
    assert len(chunks) > 0
    assert chunks[0]["page_number"] == 1
    assert "text" in chunks[0]
    assert "chunk_index" in chunks[0]

def test_extract_text_empty_pdf():
    # Empty bytes should safely return empty page list without crashing
    pages = extract_text_from_pdf(b"")
    assert pages == []
