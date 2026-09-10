"""Shared context builder for study tasks (quiz / flashcards / essay).

Replaces the old pattern of embedding an arbitrary query string containing
the document UUID (which produces a meaningless vector) with stratified
sampling across the document: head / middle / tail sections are covered so
generated questions and flashcards span the whole material.
"""

import logging

logger = logging.getLogger("worker.study_context")

# Hard ceiling for context chars sent to the AI service (Gemini 1M ctx —
# 20k chars ≈ 5k tokens, cheap and safe).
MAX_CONTEXT_CHARS = 20_000


def build_document_context(
    document_id: str,
    *,
    max_chars: int = MAX_CONTEXT_CHARS,
    strata: int = 3,
    per_stratum_limit: int = 12,
) -> tuple[str, int]:
    """Fetch chunks spread across the document and join into context text.

    Returns (context_text, total_chunks_seen).
    """
    from src.utils.embeddings import generate_embedding
    from src.utils.qdrant_client import get_qdrant_client, search_similar

    # Probe query: neutral academic phrasing so dense search returns
    # representative content rather than UUID noise.
    probe = (
        "key concepts definitions summary main ideas important facts "
        "questions and answers explained"
    )
    query_vector = generate_embedding(probe)
    # Pull a wide pool covering the WHOLE document:
    # 1) scroll the full ordered chunk list (exact head/middle/tail coverage),
    # 2) union with semantic probe hits (relevance).
    # Scroll avoids dense-search bias on 300+ page docs where top-60
    # semantic hits cluster inside a few chapters.
    pool: list[dict] = []
    try:
        scroll_client = get_qdrant_client()
        from qdrant_client.models import FieldCondition as _FC
        from qdrant_client.models import Filter as _F
        from qdrant_client.models import MatchValue as _MV

        doc_filter = _F(must=[_FC(key="document_id", match=_MV(value=document_id))])
        offset = None
        # Cap scroll at ~400 points — enough to stratify even 300+ page
        # books without OOM on the worker.
        while len(pool) < 400:
            batch, offset = scroll_client.scroll(
                collection_name="document_chunks",
                scroll_filter=doc_filter,
                limit=100,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            if not batch:
                break
            for p in batch:
                pool.append({"id": str(p.id), "score": 1.0, "payload": p.payload or {}})
            if offset is None:
                break
    except Exception as exc:
        logger.warning("study_context scroll failed for %s: %s", document_id, exc)
        pool = []
    # Union with semantic probe hits so highly relevant chunks are included
    # even if the scroll cap truncated part of the document.
    try:
        probe_hits = search_similar(query_vector, document_id=document_id, limit=60)
    except Exception:
        probe_hits = []
    seen_ids = {r.get("id") for r in pool}
    for h in probe_hits:
        if h.get("id") not in seen_ids:
            pool.append(h)
            seen_ids.add(h.get("id"))
    if not pool:
        return "", 0

    try:
        client = get_qdrant_client()
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        total_seen = client.count(
            collection_name="document_chunks",
            count_filter=Filter(
                must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]
            ),
        ).count
    except Exception as exc:
        logger.warning("study_context count failed for %s: %s", document_id, exc)
        total_seen = len(pool)

    # Sort pool by chunk_index so strata map to doc order (head/middle/tail).
    def _idx(r: dict) -> int:
        try:
            return int((r.get("payload") or {}).get("chunk_index", 0))
        except (TypeError, ValueError):
            return 0

    ordered = sorted(pool, key=_idx)
    n = len(ordered)
    # Evenly-spaced sampling inside each stratum (step = len/quota) so
    # picked chunks span the FULL segment — with 300+ chunks, taking the
    # first 12 per segment only covered the segment head (the screenshot bug:
    # generic/intro-only questions).
    picked: list[dict] = []
    if n <= per_stratum_limit * strata:
        picked = ordered
    else:
        size = n // strata
        for s in range(strata):
            start = s * size
            end = n if s == strata - 1 else (s + 1) * size
            segment = ordered[start:end]
            quota = min(per_stratum_limit, len(segment))
            if quota >= len(segment):
                picked.extend(segment)
            else:
                step = len(segment) / quota
                idxs = {int(i * step) for i in range(quota)}
                picked.extend([c for i, c in enumerate(segment) if i in idxs])
        picked = sorted(picked, key=_idx)

    parts: list[str] = []
    used = 0
    for r in picked:
        payload = r.get("payload") or {}
        text = (payload.get("text") or "").strip()
        if not text:
            continue
        page = payload.get("page_number")
        label = f"[Trang {page}] " if page else ""
        piece = f"{label}{text}"
        if used + len(piece) + 2 > max_chars:
            break
        parts.append(piece)
        used += len(piece) + 2

    return "\n\n".join(parts), total_seen
