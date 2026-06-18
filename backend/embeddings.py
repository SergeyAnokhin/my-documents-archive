"""Semantic search via embeddings and ChromaDB.

Generates embedding vectors for document text and enables meaning-based search.
Runs locally — no API calls needed for search."""

import logging
from pathlib import Path
from typing import Optional

from backend.config import DB_DIR

logger = logging.getLogger(__name__)

CHROMA_PATH = DB_DIR / "chroma"
COLLECTION_NAME = "documents"
_embedding_model = None
_chroma_client = None


def _get_embedding_model():
    """Lazy-load the sentence transformer model."""
    global _embedding_model
    if _embedding_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            # Use a small multilingual model (supports Russian, French, English)
            _embedding_model = SentenceTransformer(
                "intfloat/multilingual-e5-small",
                device="cpu",
            )
            logger.info("Embedding model loaded")
        except Exception as e:
            logger.warning("Failed to load embedding model: %s", e)
            return None
    return _embedding_model


def _get_chroma():
    """Lazy-load ChromaDB client."""
    global _chroma_client
    if _chroma_client is None:
        try:
            import chromadb
            CHROMA_PATH.mkdir(parents=True, exist_ok=True)
            _chroma_client = chromadb.PersistentClient(path=str(CHROMA_PATH))
            logger.info("ChromaDB client initialized")
        except Exception as e:
            logger.warning("Failed to initialize ChromaDB: %s", e)
            return None
    return _chroma_client


def _get_collection():
    """Get or create the documents collection."""
    client = _get_chroma()
    if client is None:
        return None
    try:
        return client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
    except Exception as e:
        logger.warning("ChromaDB collection error: %s", e)
        return None


def index_embedding(doc_id: str, text: str):
    """Generate and store embedding for a document.

    Uses the document's summary + OCR text as the source.
    Removes any existing embedding for this doc first."""
    model = _get_embedding_model()
    collection = _get_collection()
    if model is None or collection is None:
        return

    if not text or not text.strip():
        return

    try:
        # Remove existing
        try:
            collection.delete(ids=[doc_id])
        except Exception:
            pass

        # Encode text
        embedding = model.encode(
            text[:2000],
            normalize_embeddings=True,
            show_progress_bar=False,
        ).tolist()

        collection.add(
            ids=[doc_id],
            embeddings=[embedding],
            metadatas=[{"doc_id": doc_id}],
        )
    except Exception as e:
        logger.warning("Embedding index failed for %s: %s", doc_id, e)


def semantic_search(query: str, limit: int = 20) -> list[dict]:
    """Search documents by semantic meaning. Returns list of {id, score}."""
    model = _get_embedding_model()
    collection = _get_collection()
    if model is None or collection is None:
        return []

    try:
        query_embedding = model.encode(
            query,
            normalize_embeddings=True,
            show_progress_bar=False,
        ).tolist()

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(limit, collection.count()),
        )

        if not results["ids"] or not results["ids"][0]:
            return []

        return [
            {
                "id": doc_id,
                "score": round(1.0 - distance, 4),  # Convert distance to similarity
            }
            for doc_id, distance in zip(results["ids"][0], results["distances"][0])
        ]
    except Exception as e:
        logger.warning("Semantic search failed: %s", e)
        return []


def is_available() -> bool:
    """Check if embeddings/chroma are usable."""
    return _get_embedding_model() is not None and _get_chroma() is not None
