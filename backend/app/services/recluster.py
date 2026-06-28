"""
Cluster-based document recategorization.

Pipeline:
  1. Load all analyzed documents with a non-empty summary.
  2. Clean summary: strip tags, person/org names, dates.
  3. Embed cleaned texts (reuse sentence-transformers model from embeddings.py).
  4. Auto-select cluster count k via silhouette score.
  5. K-means clustering.
  6. Pick 3-5 representative docs per cluster (nearest to centroid).
  7. Ask LLM to name each cluster → type slug + Lucide icon.
  8. Apply: old document_type → tags (if meaningful), new type set.
"""

import logging
import math
import re
from typing import Optional

log = logging.getLogger(__name__)

# ── Summary cleaning ──────────────────────────────────────────────────────────

_DATE_RE = re.compile(
    r'\b\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4}\b'           # DD.MM.YYYY etc.
    r'|\b\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2}\b'            # YYYY-MM-DD
    r'|\b\d{1,2}\s+(?:january|february|march|april|may|june|july|august|'
    r'september|october|november|december)\s+\d{4}\b'   # DD Month YYYY (EN)
    r'|\b(?:january|february|march|april|may|june|july|august|'
    r'september|october|november|december)\s+\d{4}\b'   # Month YYYY (EN)
    r'|\b\d{1,2}\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|'
    r'сентября|октября|ноября|декабря)\s+\d{4}\b'       # DD Месяц ГГГГ (RU)
    r'|\b(?:января|февраля|марта|апреля|мая|июня|июля|августа|'
    r'сентября|октября|ноября|декабря)\s+\d{4}\b'       # Месяц ГГГГ (RU)
    r'|\b\d{1,2}\s+(?:janvier|février|mars|avril|mai|juin|juillet|août|'
    r'septembre|octobre|novembre|décembre)\s+\d{4}\b'   # DD mois YYYY (FR)
    r'|\b(?:janvier|février|mars|avril|mai|juin|juillet|août|'
    r'septembre|octobre|novembre|décembre)\s+\d{4}\b'   # mois YYYY (FR)
    r'|\b(?:19|20)\d{2}\b',                              # standalone years 1900-2099
    re.IGNORECASE,
)


def _strip_for_clustering(
    summary: str,
    tags: list,
    person_first: Optional[str],
    person_last: Optional[str],
    organization: Optional[str],
) -> str:
    """Return a cleaned version of summary for clustering."""
    text = summary or ""

    text = _DATE_RE.sub(" ", text)

    for token in filter(None, [person_first, person_last, organization]):
        if len(token) > 2:
            text = re.sub(r"\b" + re.escape(token) + r"\b", " ", text, flags=re.IGNORECASE)

    for tag in (tags or []):
        if tag and len(tag) > 2:
            text = re.sub(r"\b" + re.escape(tag) + r"\b", " ", text, flags=re.IGNORECASE)

    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) >= 20 else (summary or "")  # fallback to original if stripped too short


# ── K selection ───────────────────────────────────────────────────────────────

def _k_range(n: int) -> tuple[int, int]:
    k_min = max(5, int(math.sqrt(n / 50)))
    k_max = min(35, int(math.sqrt(n / 5)))
    return k_min, max(k_min + 2, k_max)


def _best_k(embeddings, k_min: int, k_max: int) -> int:
    """Try ~8 k values and return the one with highest silhouette score."""
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score

    n = len(embeddings)
    best_k, best_score = k_min, -1.0

    step = max(1, (k_max - k_min) // 7)
    candidates = list(range(k_min, k_max + 1, step))
    if k_max not in candidates:
        candidates.append(k_max)

    for k in candidates:
        if k >= n:
            break
        km = KMeans(n_clusters=k, random_state=42, n_init=5, max_iter=100)
        labels = km.fit_predict(embeddings)
        if len(set(labels)) < 2:
            continue
        score = silhouette_score(
            embeddings, labels,
            sample_size=min(2000, n),
            random_state=42,
        )
        log.debug("Silhouette k=%d → %.4f", k, score)
        if score > best_score:
            best_score, best_k = score, k

    log.info("Selected k=%d (silhouette=%.4f)", best_k, best_score)
    return best_k


# ── Cluster helpers ───────────────────────────────────────────────────────────

def _representative_indices(embeddings, labels, k: int, n_repr: int = 5) -> dict[int, list[int]]:
    """For each cluster return indices of docs nearest to the centroid."""
    import numpy as np

    result: dict[int, list[int]] = {}
    for cid in range(k):
        idx = [i for i, lbl in enumerate(labels) if lbl == cid]
        if not idx:
            result[cid] = []
            continue
        vecs = embeddings[idx]
        centroid = vecs.mean(axis=0)
        dists = ((vecs - centroid) ** 2).sum(axis=1)
        top = dists.argsort()[:n_repr]
        result[cid] = [idx[i] for i in top]
    return result


async def _name_cluster(summaries: list[str], db) -> tuple[str, str]:
    """Ask LLM to name one cluster. Returns (type_slug, lucide_icon)."""
    import json
    from .ai_analysis import _get_providers, run_text
    from .ai_common import strip_code_fences

    providers = _get_providers(db)
    if not providers:
        return ("unclassified", "FileText")

    numbered = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(summaries[:5]))
    user_msg = (
        "The following documents belong to the same group in a personal archive:\n\n"
        f"{numbered}\n\n"
        "Based on their content, propose:\n"
        '1. A short document type slug (1–3 words, lowercase, underscores, '
        'e.g. "tax_return", "insurance_policy", "passport", "bank_statement")\n'
        '2. A Lucide icon name that fits the content '
        '(e.g. "FileText", "Briefcase", "CreditCard", "Home", "Heart", '
        '"GraduationCap", "Car", "Shield", "Receipt", "Building2")\n\n'
        'Reply with JSON only: {"type": "...", "icon": "..."}'
    )

    try:
        text, _, _, _ = await run_text(providers[0], "You are a document archivist.", user_msg)
        data = json.loads(strip_code_fences(text))
        type_slug = data.get("type", "unclassified").lower().replace(" ", "_")
        icon = data.get("icon", "FileText")
        return (type_slug, icon)
    except Exception as e:
        log.warning("Cluster naming failed: %s", e)
        return ("unclassified", "FileText")


def _apply_new_type(doc, new_type: str) -> None:
    """Set document_type; preserve old type in tags if it was meaningful and changed."""
    old_type = doc.document_type
    if old_type and old_type not in ("unclassified", "other") and old_type != new_type:
        existing = list(doc.tags or [])
        if old_type not in existing:
            existing.append(old_type)
        doc.tags = existing
    doc.document_type = new_type
    doc.classification_source = "auto"
    doc.manually_classified = False


def _save_cluster_icons(cluster_names: dict[int, tuple[str, str]], db) -> None:
    """Persist icon suggestions for new type slugs in AppSettings."""
    import json
    from ..models import AppSettings

    try:
        row = db.query(AppSettings).filter(AppSettings.key == "custom_type_icons").first()
        existing: dict = json.loads(row.value) if row and row.value else {}

        changed = False
        for _, (type_slug, icon) in cluster_names.items():
            if type_slug and type_slug != "unclassified" and type_slug not in existing:
                existing[type_slug] = icon
                changed = True

        if not changed:
            return
        if row:
            row.value = json.dumps(existing)
        else:
            db.add(AppSettings(key="custom_type_icons", value=json.dumps(existing)))
        db.commit()
    except Exception as e:
        log.warning("Could not save cluster icons: %s", e)


# ── Main entry point ──────────────────────────────────────────────────────────

async def run_recluster(task_id: Optional[int] = None) -> dict:
    """
    Full clustering pipeline.
    Returns {"total": int, "clusters": int, "applied": int}.
    """
    import numpy as np
    from sklearn.cluster import KMeans
    from ..database import SessionLocal
    from ..models import Document
    from .embeddings import _get_model

    def _tlog(msg: str, level: str = "info") -> None:
        if task_id is not None:
            try:
                from ..services.task_runtime import log_task
                log_task(task_id, msg, level)
            except Exception:
                pass
        log.info("recluster: %s", msg)

    def _progress(current: int, total: int) -> None:
        if task_id is not None:
            try:
                from ..services.task_runtime import set_progress
                set_progress(task_id, current, total)
            except Exception:
                pass

    db = SessionLocal()
    try:
        docs = (
            db.query(Document)
            .filter(
                Document.is_deleted == False,
                Document.ocr_status == "done",
                Document.analysis_status == "done",
                Document.summary.isnot(None),
                Document.summary != "",
            )
            .all()
        )

        if not docs:
            _tlog("No documents with summaries found — nothing to cluster.", "warning")
            return {"total": 0, "clusters": 0, "applied": 0}

        _tlog(f"Loaded {len(docs)} documents for clustering")

        # Step 1: clean summaries
        cleaned = [
            _strip_for_clustering(
                d.summary,
                d.tags or [],
                getattr(d, "person_first_name", None),
                getattr(d, "person_last_name", None),
                getattr(d, "organization", None),
            )
            for d in docs
        ]

        # Step 2: embed
        _tlog("Embedding document summaries…")
        model = _get_model()
        embeddings = model.encode(
            cleaned,
            normalize_embeddings=True,
            batch_size=64,
            show_progress_bar=False,
        )
        embeddings = np.array(embeddings, dtype=np.float32)

        # Step 3: select k
        n = len(docs)
        if n < 5:
            k = n
        else:
            k_min, k_max = _k_range(n)
            _tlog(f"Selecting k in [{k_min}, {k_max}] via silhouette score…")
            k = _best_k(embeddings, k_min, k_max)

        _tlog(f"Clustering {n} documents into k={k} groups…")

        # Step 4: k-means
        km = KMeans(n_clusters=k, random_state=42, n_init=10, max_iter=300)
        labels = km.fit_predict(embeddings)

        # Step 5: representative docs per cluster
        repr_map = _representative_indices(embeddings, labels, k)

        # Step 6: name each cluster via LLM
        _tlog(f"Naming {k} clusters via LLM…")
        cluster_names: dict[int, tuple[str, str]] = {}
        for cid in range(k):
            repr_summaries = [cleaned[i] for i in repr_map.get(cid, []) if cleaned[i].strip()]
            type_slug, icon = await _name_cluster(repr_summaries, db)
            cluster_names[cid] = (type_slug, icon)
            _tlog(f"  Cluster {cid + 1}/{k} → {type_slug}")
            _progress(cid + 1, k)

        # Step 7: save icons for new types
        _save_cluster_icons(cluster_names, db)

        # Step 8: apply types to documents
        _tlog("Applying new types…")
        applied = 0
        for doc, label in zip(docs, labels):
            new_type, _ = cluster_names[int(label)]
            _apply_new_type(doc, new_type)
            applied += 1
        db.commit()

        _tlog(f"Done — {applied} documents recategorized into {k} clusters")
        return {"total": len(docs), "clusters": k, "applied": applied}

    except Exception as e:
        log.error("run_recluster failed: %s", e)
        raise
    finally:
        db.close()
