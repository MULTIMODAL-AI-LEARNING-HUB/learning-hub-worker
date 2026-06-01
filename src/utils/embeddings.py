"""Embedding utility using Groq API."""

import hashlib
import math


def generate_embedding(text: str, dimension: int = 384) -> list[float]:
    """Generate a deterministic pseudo-embedding from text.
    In production, use Groq/OpenAI embedding API. This is a local fallback."""
    h = hashlib.sha512(text.encode("utf-8")).digest()
    vec = []
    for i in range(0, min(len(h), dimension * 4), 4):
        chunk = h[i : i + 4]
        val = int.from_bytes(chunk, "big") / (2**32)
        vec.append(val * 2 - 1)
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]
