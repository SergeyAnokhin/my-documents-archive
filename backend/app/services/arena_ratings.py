"""
Fetch and cache LM Arena (Chatbot Arena / lmarena.ai) leaderboard ratings.

Ratings are stored as {model_id: {text: 0-5, vision: 0-5}} in AppSettings.
The "Update Ratings" button in the admin panel calls refresh_ratings().
Falls back to hardcoded approximate values if the live fetch fails.
"""
import json
import logging
from typing import Optional
import httpx

log = logging.getLogger(__name__)

SETTINGS_KEY = "arena_ratings"

# Approximate ratings (text_score, vision_score) on 0-100 scale based on
# Chatbot Arena Elo leaderboard as of Q2 2025.
# Vision score 0 means the model doesn't support vision / not benchmarked.
_HARDCODED: dict[str, tuple[float, float]] = {
    "claude-opus-4-8":                (97, 95),
    "claude-sonnet-4-6":              (91, 92),
    "claude-3-5-sonnet-20241022":     (91, 91),
    "claude-3-5-haiku-20241022":      (76, 78),
    "claude-haiku-4-5-20251001":      (76, 78),
    "claude-3-opus-20240229":         (86, 85),
    "gpt-4o":                         (93, 94),
    "gpt-4o-mini":                    (79, 80),
    "gpt-4-turbo":                    (87, 88),
    "gpt-3.5-turbo":                  (64, 0),
    "o1-mini":                        (88, 0),
    "o3-mini":                        (91, 0),
    "gemini-2.5-pro-preview-06-05":   (93, 91),
    "gemini-2.5-flash-preview-05-20": (85, 85),
    "gemini-2.5-pro":                 (93, 91),
    "gemini-2.5-flash":               (85, 85),
    "gemini-2.5-flash-lite":          (78, 78),
    "gemini-1.5-pro":                 (83, 83),
    "gemini-1.5-pro-002":             (83, 83),
    "gemini-1.5-flash":               (73, 75),
    "gemini-1.5-flash-002":           (73, 75),
    "gemini-2.0-flash":               (79, 80),
    "gemini-2.0-flash-lite":          (68, 70),
    "gemini-2.0-flash-exp":           (79, 80),
    "gemini-3.0-flash":               (82, 82),
    "gemini-3.1-flash-lite-preview":  (78, 78),
    "gemini-3.1-flash-preview":       (82, 82),
    # Mistral
    "mistral-large-latest":           (78, 0),
    "mistral-medium-latest":          (72, 0),
    "mistral-small-latest":           (68, 0),
    "pixtral-large-latest":           (78, 76),
    "pixtral-12b-2409":               (68, 66),
    "deepseek-chat":                  (83, 0),
    "deepseek-reasoner":              (91, 0),
    # OpenRouter model IDs (provider/model format)
    "openai/gpt-4o":                  (93, 94),
    "openai/gpt-4o-mini":             (79, 80),
    "anthropic/claude-3.5-sonnet":    (91, 91),
    "google/gemini-pro-1.5":          (83, 83),
    "google/gemini-flash-1.5":        (73, 75),
    "deepseek/deepseek-chat":         (83, 0),
    "deepseek/deepseek-r1":           (91, 0),
    "mistralai/mistral-large":        (78, 0),
    "meta-llama/llama-3.1-70b-instruct": (80, 0),
    "meta-llama/llama-3.1-405b-instruct": (85, 0),
}


def _score_to_stars(score: float) -> int:
    """Convert 0-100 quality score to 0-5 stars."""
    if score >= 92: return 5
    if score >= 82: return 4
    if score >= 70: return 3
    if score >= 55: return 2
    if score > 0:   return 1
    return 0


def _hardcoded_stars() -> dict[str, dict[str, int]]:
    return {
        mid: {"text": _score_to_stars(t), "vision": _score_to_stars(v)}
        for mid, (t, v) in _HARDCODED.items()
    }


def get_cached(db) -> dict[str, dict[str, int]]:
    """Return cached ratings, or hardcoded fallback."""
    from ..models import AppSettings
    row = db.query(AppSettings).filter(AppSettings.key == SETTINGS_KEY).first()
    if row and row.value:
        try:
            return json.loads(row.value)
        except Exception:
            pass
    return _hardcoded_stars()


async def refresh_ratings(db) -> dict[str, dict[str, int]]:
    """
    Fetch fresh ratings from LM Arena / HuggingFace dataset.
    Updates the AppSettings cache and returns the result.
    Falls back to hardcoded data on any error.
    """
    try:
        ratings = await _fetch_from_huggingface()
        # Merge with hardcoded so we always have data for well-known models
        merged = _hardcoded_stars()
        merged.update(ratings)
        _save_to_db(db, merged)
        log.info("Arena ratings refreshed: %d models", len(merged))
        return merged
    except Exception as e:
        log.warning("Arena ratings fetch failed: %s. Using hardcoded.", e)
        fallback = _hardcoded_stars()
        _save_to_db(db, fallback)
        return fallback


def _save_to_db(db, ratings: dict) -> None:
    from ..models import AppSettings
    row = db.query(AppSettings).filter(AppSettings.key == SETTINGS_KEY).first()
    payload = json.dumps(ratings)
    if row:
        row.value = payload
    else:
        db.add(AppSettings(key=SETTINGS_KEY, value=payload))
    db.commit()


async def _fetch_from_huggingface() -> dict[str, dict[str, int]]:
    """
    Fetch from HuggingFace Datasets Server API for lmsys/chatbot_arena_leaderboard.
    The dataset is public and free; no token needed.
    """
    url = (
        "https://datasets-server.huggingface.co/rows"
        "?dataset=lmsys%2Fchatbot_arena_leaderboard"
        "&config=default&split=train&offset=0&length=200"
    )
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url)
        r.raise_for_status()

    rows_data = r.json().get("rows", [])
    if not rows_data:
        raise ValueError("Empty dataset response")

    sample_row = rows_data[0].get("row", {})

    # Discover column names (dataset schema can vary)
    all_cols = list(sample_row.keys())

    model_col = _pick_col(all_cols, ["key", "model", "Model", "model_name", "name"])
    score_col  = _pick_col(all_cols, ["Arena Score", "Arena Elo", "Elo rating", "elo_rating", "rating"])
    vision_col = _pick_col(all_cols, ["Vision Arena Score", "Vision Elo", "vision_arena_score", "vision_score"])

    if not model_col or not score_col:
        raise ValueError(f"Unrecognised schema. Columns: {all_cols[:15]}")

    scores = [
        row["row"][score_col]
        for row in rows_data
        if isinstance(row["row"].get(score_col), (int, float))
    ]
    if not scores:
        raise ValueError("No numeric scores in dataset")

    min_s, max_s = min(scores), max(scores)
    span = (max_s - min_s) or 1.0

    result: dict[str, dict[str, int]] = {}
    for entry in rows_data:
        row = entry.get("row", {})
        model_id = str(row.get(model_col, "")).strip().lower()
        if not model_id:
            continue
        raw = row.get(score_col) or 0
        if not isinstance(raw, (int, float)):
            continue
        norm = (raw - min_s) / span * 100
        text_stars = _score_to_stars(norm)

        vision_stars = 0
        if vision_col:
            vraw = row.get(vision_col) or 0
            if isinstance(vraw, (int, float)) and vraw > 0:
                vnorm = (vraw - min_s) / span * 100
                vision_stars = _score_to_stars(vnorm)

        result[model_id] = {"text": text_stars, "vision": vision_stars}

    return result


def _pick_col(cols: list[str], candidates: list[str]) -> Optional[str]:
    """Return first candidate that exists in cols (case-insensitive)."""
    cols_lower = {c.lower(): c for c in cols}
    for c in candidates:
        if c.lower() in cols_lower:
            return cols_lower[c.lower()]
    return None
