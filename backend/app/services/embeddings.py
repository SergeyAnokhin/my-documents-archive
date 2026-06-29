"""
Embeddings service — generates multilingual document vectors for semantic search.

Model: paraphrase-multilingual-MiniLM-L12-v2 (~420 MB, supports RU/FR/EN).
Storage: ChromaDB PersistentClient at library/.docintell/chroma/

Public API:
  embed_document(doc_id, text)       — upsert vector into collection
  search_similar(query, n_results)   — return doc_ids ordered by similarity
  collection_count()                 — how many docs have embeddings
"""

import logging
from typing import Optional

from ..config import settings

log = logging.getLogger(__name__)

_model = None   # SentenceTransformer, lazy init
_chroma = None  # chromadb.PersistentClient, lazy init
_coll = None    # chromadb.Collection, lazy init


# ── Public API ────────────────────────────────────────────────────────────────

def embed_document(doc_id: int, text: str) -> None:
    """Generate and upsert embedding for a document. Idempotent."""
    if not text.strip():
        return
    model = _get_model()
    coll  = _get_collection()
    vector = model.encode(text[:2000], normalize_embeddings=True).tolist()
    coll.upsert(
        ids=[str(doc_id)],
        embeddings=[vector],
        documents=[text[:300]],
        metadatas=[{"doc_id": doc_id}],
    )


def search_similar(query: str, n_results: int = 50) -> list[int]:
    """
    Return up to n_results document IDs ordered by cosine similarity to query.
    Returns empty list if collection is empty or model unavailable.
    """
    return [doc_id for doc_id, _ in search_similar_scored(query, n_results)]


def search_similar_scored(query: str, n_results: int = 50) -> list[tuple[int, float]]:
    """
    Like search_similar, but also returns each match's cosine *distance*
    (0.0 = identical, 2.0 = opposite; similarity = 1 - distance).
    Ordered closest-first. Returns [] if collection is empty or model unavailable.
    Used by the /ask retrieval logging to show why a document ranked where it did.
    """
    try:
        model = _get_model()
        coll  = _get_collection()
        count = coll.count()
        if count == 0:
            return []
        n = min(n_results, count)
        vector = model.encode(query, normalize_embeddings=True).tolist()
        results = coll.query(query_embeddings=[vector], n_results=n)
        ids   = results["ids"][0]
        dists = (results.get("distances") or [[None] * len(ids)])[0]
        return [
            (int(mid), float(dist) if dist is not None else None)
            for mid, dist in zip(ids, dists)
        ]
    except Exception as e:
        log.warning("Semantic search failed: %s", e)
        return []


def collection_count() -> int:
    """Return number of documents currently embedded."""
    try:
        return _get_collection().count()
    except Exception:
        return 0


def embedded_ids() -> set[int]:
    """Return the set of document IDs that currently have an embedding."""
    try:
        got = _get_collection().get(include=[])  # ids only — no vectors/documents
        return {int(i) for i in got.get("ids", [])}
    except Exception:
        return set()


# ── Lazy init ─────────────────────────────────────────────────────────────────

def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        log.info("Loading embedding model paraphrase-multilingual-MiniLM-L12-v2…")
        _model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
        log.info("Embedding model loaded.")
    return _model


def _get_collection():
    global _chroma, _coll
    if _coll is None:
        import chromadb
        settings.chroma_dir.mkdir(parents=True, exist_ok=True)
        _chroma = chromadb.PersistentClient(path=str(settings.chroma_dir))
        _coll = _chroma.get_or_create_collection(
            name="documents",
            metadata={"hnsw:space": "cosine"},
        )
    return _coll
