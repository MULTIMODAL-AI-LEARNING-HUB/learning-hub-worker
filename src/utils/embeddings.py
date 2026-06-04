"""Real embedding generation using sentence-transformers."""

from typing import Optional
from sentence_transformers import SentenceTransformer

_model: Optional[SentenceTransformer] = None


def get_embedding_model() -> SentenceTransformer:
    """Get or load the SentenceTransformer model singleton."""
    global _model
    if _model is None:
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def generate_embedding(text: str, dimension: int = 384) -> list[float]:
    """Generate a real 384-dimensional vector embedding for the given text."""
    model = get_embedding_model()
    embedding = model.encode(text)
    return [float(v) for v in embedding]
