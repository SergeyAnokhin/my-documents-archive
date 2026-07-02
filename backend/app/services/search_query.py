"""Text-query helpers shared by fulltext/hybrid search and the /ask QA pipeline.

Split out of routers/search.py to keep that router focused on endpoints.
Pure query-building/merging logic — no endpoint or response assembly here.
"""
from sqlalchemy import or_, String
from typing import Optional
import re

from ..models import Document


def _parse_query(query: str) -> tuple[list[str], list[str]]:
    """Split query into exact phrases (quoted) and individual words.

    Example: `договор "Иванов Иван" 2024` → (['Иванов Иван'], ['договор', '2024'])
    """
    phrases = re.findall(r'"([^"]+)"', query)
    remainder = re.sub(r'"[^"]+"', '', query)
    words = [w.strip() for w in remainder.split() if w.strip()]
    return phrases, words


def _apply_text_filter(q, phrases: list[str], words: list[str]):
    """Add LIKE filters for all phrases and words to a SQLAlchemy query."""
    COLS = lambda like: or_(
        Document.filename.ilike(like),
        Document.ocr_text.ilike(like),
        Document.summary.ilike(like),
        Document.document_type.ilike(like),
        Document.tags.cast(String).ilike(like),
        Document.person_first_name.ilike(like),
        Document.person_last_name.ilike(like),
        Document.organization.ilike(like),
    )
    for phrase in phrases:
        q = q.filter(COLS(f"%{phrase}%"))
    for word in words:
        q = q.filter(COLS(f"%{word}%"))
    return q


def _highlight(text: Optional[str], query: str) -> Optional[str]:
    """Extract a ~200 char snippet around the first query hit."""
    if not text or not query:
        return None
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    m = pattern.search(text)
    if not m:
        return text[:200]
    start = max(0, m.start() - 80)
    end   = min(len(text), m.end() + 120)
    snippet = text[start:end]
    return ("…" if start > 0 else "") + snippet + ("…" if end < len(text) else "")


def _semantic_scored(query: str, n: int) -> list[tuple[int, float]]:
    try:
        from .embeddings import search_similar_scored
        return search_similar_scored(query, n_results=n)
    except Exception:
        return []


def _fulltext_ids(base_query, query: str) -> set[int]:
    phrases, words = _parse_query(query)
    q = _apply_text_filter(base_query, phrases, words)
    return {d.id for d in q.with_entities(Document.id).all()}


def _merge_hybrid(sem_ids: list[int], ft_ids: set[int]) -> list[int]:
    """Merge semantic + fulltext results: both-sets first, then semantic-only, then ft-only."""
    seen: set[int] = set()
    result: list[int] = []

    # Tier 1: in both
    for did in sem_ids:
        if did in ft_ids:
            result.append(did)
            seen.add(did)
    # Tier 2: semantic only
    for did in sem_ids:
        if did not in seen:
            result.append(did)
            seen.add(did)
    # Tier 3: fulltext only
    for did in ft_ids:
        if did not in seen:
            result.append(did)

    return result


# ── Transliteration helpers ────────────────────────────────────────────────────

_CYR_TO_LAT: dict[str, str] = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
    'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
}

# Common first-name Latin→Cyrillic map for cross-script name matching
_LAT_NAME_TO_CYR: dict[str, str] = {
    'sergey': 'сергей', 'sergei': 'сергей', 'serge': 'сергей',
    'alexey': 'алексей', 'aleksey': 'алексей', 'alexei': 'алексей',
    'ivan': 'иван', 'anna': 'анна', 'igor': 'игорь', 'olga': 'ольга',
    'andrey': 'андрей', 'andrei': 'андрей',
    'natasha': 'наташа', 'natalia': 'наталья', 'natalya': 'наталья',
    'mikhail': 'михаил', 'michael': 'михаил',
    'nikolay': 'николай', 'nikolai': 'николай', 'nicolas': 'николай',
    'vladimir': 'владимир',
    'dmitry': 'дмитрий', 'dmitri': 'дмитрий', 'dmitriy': 'дмитрий',
    'maxim': 'максим', 'artem': 'артем', 'denis': 'денис',
    'alexander': 'александр', 'alexandre': 'александр',
}


def _transliterate_cyr_to_lat(word: str) -> str:
    return ''.join(_CYR_TO_LAT.get(c, c) for c in word.lower())


def _expand_fulltext_query(query: str) -> list[str]:
    """Return [original, transliterated-variant] for cross-script name matching."""
    variants = [query]
    words = query.split()
    translated: list[str] = []
    for word in words:
        w = word.lower()
        if any(c in _CYR_TO_LAT for c in w):
            translated.append(_transliterate_cyr_to_lat(w))
        elif w in _LAT_NAME_TO_CYR:
            translated.append(_LAT_NAME_TO_CYR[w])
        else:
            translated.append(w)
    translit_query = ' '.join(translated)
    if translit_query.lower() != query.lower():
        variants.append(translit_query)
    return variants
