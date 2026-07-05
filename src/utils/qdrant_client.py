"""Qdrant client wrapper."""

from qdrant_client import QdrantClient as QC
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PointStruct,
    VectorParams,
)
from src.core.config import settings

_client: QC | None = None
COLLECTION_NAME = "document_chunks"
VECTOR_SIZE = 384


def get_qdrant_client() -> QC:
    global _client
    if _client is None:
        if settings.QDRANT_URL:
            _client = QC(
                url=settings.QDRANT_URL,
                api_key=settings.QDRANT_API_KEY,
            )
        else:
            _client = QC(
                host=settings.QDRANT_HOST,
                port=settings.QDRANT_PORT,
            )
        _ensure_collection(_client)
    return _client


def _ensure_collection(client: QC) -> None:
    collections = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME not in collections:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )


def upsert_chunks(chunks: list[dict]) -> None:
    client = get_qdrant_client()
    points = [
        PointStruct(
            id=chunk["id"],
            vector=chunk["vector"],
            payload={
                "document_id": chunk["document_id"],
                "user_id": chunk.get("user_id"),
                "chunk_index": chunk["chunk_index"],
                "text": chunk["text"],
                "page_number": chunk.get("page_number"),
                "metadata": chunk.get("metadata"),
                "course_id": chunk.get("course_id"),
                "lesson_id": chunk.get("lesson_id"),
                "material_id": chunk.get("material_id"),
                "source_type": chunk.get("source_type", "personal_doc"),
            },
        )
        for chunk in chunks
    ]
    client.upsert(collection_name=COLLECTION_NAME, points=points)


def search_similar(
    query_vector: list[float],
    document_id: str | None = None,
    course_id: str | None = None,
    lesson_id: str | None = None,
    material_id: str | None = None,
    material_ids: list[str] | None = None,
    source_type: str | None = None,
    user_id: str | None = None,
    limit: int = 10
) -> list[dict]:
    client = get_qdrant_client()
    conditions = []
    if document_id:
        conditions.append(FieldCondition(key="document_id", match=MatchValue(value=document_id)))
    if course_id:
        conditions.append(FieldCondition(key="course_id", match=MatchValue(value=course_id)))
    if lesson_id:
        conditions.append(FieldCondition(key="lesson_id", match=MatchValue(value=lesson_id)))
    if material_id:
        conditions.append(FieldCondition(key="material_id", match=MatchValue(value=material_id)))
    if material_ids:
        conditions.append(FieldCondition(key="material_id", match=MatchAny(any=material_ids)))
    if source_type:
        conditions.append(FieldCondition(key="source_type", match=MatchValue(value=source_type)))
    if user_id:
        conditions.append(FieldCondition(key="user_id", match=MatchValue(value=user_id)))

    query_filter = Filter(must=conditions) if conditions else None

    results = client.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        query_filter=query_filter,
        limit=limit,
    )
    return [
        {
            "id": r.id,
            "score": r.score,
            "payload": r.payload,
        }
        for r in results.points
    ]


def delete_by_document_id(document_id: str) -> None:
    client = get_qdrant_client()
    client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=Filter(
            must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]
        ),
    )
