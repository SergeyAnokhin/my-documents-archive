"""
Fetch and cache LM Arena (Chatbot Arena / lmarena.ai) leaderboard ratings.

Ratings are stored as {model_id: {text: 0-5, vision: 0-5, elo: int|None}} in AppSettings.
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

# Approximate Elo scores (Chatbot Arena scale, ~1000-1400 range, Q2 2025)
_HARDCODED_ELO: dict[str, int] = {
    "claude-opus-4-8":                1375,
    "claude-sonnet-4-6":              1340,
    "claude-3-5-sonnet-20241022":     1338,
    "claude-3-5-haiku-20241022":      1240,
    "claude-haiku-4-5-20251001":      1240,
    "claude-3-opus-20240229":         1281,
    "gpt-4o":                         1355,
    "gpt-4o-mini":                    1270,
    "gpt-4-turbo":                    1295,
    "gpt-3.5-turbo":                  1170,
    "o1-mini":                        1304,
    "o3-mini":                        1342,
    "gemini-2.5-pro-preview-06-05":   1368,
    "gemini-2.5-flash-preview-05-20": 1292,
    "gemini-2.5-pro":                 1368,
    "gemini-2.5-flash":               1292,
    "gemini-2.5-flash-lite":          1246,
    "gemini-1.5-pro":                 1267,
    "gemini-1.5-pro-002":             1267,
    "gemini-1.5-flash":               1218,
    "gemini-1.5-flash-002":           1218,
    "gemini-2.0-flash":               1253,
    "gemini-2.0-flash-lite":          1195,
    "gemini-2.0-flash-exp":           1253,
    "gemini-3.0-flash":               1275,
    "mistral-large-latest":           1241,
    "deepseek-chat":                  1316,
    "deepseek-reasoner":              1352,
    "openai/gpt-4o":                  1355,
    "openai/gpt-4o-mini":             1270,
    "anthropic/claude-3.5-sonnet":    1338,
    "deepseek/deepseek-chat":         1316,
    "deepseek/deepseek-r1":           1352,
    "meta-llama/llama-3.1-405b-instruct": 1270,
}


def _score_to_stars(score: float) -> int:
    """Convert 0-100 quality score to 0-5 stars."""
    if score >= 92: return 5
    if score >= 82: return 4
    if score >= 70: return 3
    if score >= 55: return 2
    if score > 0:   return 1
    return 0


def _hardcoded_stars() -> dict[str, dict]:
    return {
        mid: {
            "text": _score_to_stars(t),
            "vision": _score_to_stars(v),
            "elo": _HARDCODED_ELO.get(mid),
        }
        for mid, (t, v) in _HARDCODED.items()
    }


def get_cached(db) -> dict[str, dict]:
    """Return cached ratings, or hardcoded fallback."""
    from ..models import AppSettings
    row = db.query(AppSettings).filter(AppSettings.key == SETTINGS_KEY).first()
    if row and row.value:
        try:
            return json.loads(row.value)
        except Exception:
            pass
    return _hardcoded_stars()


async def refresh_ratings(db) -> dict[str, dict]:
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


async def _fetch_from_huggingface() -> dict[str, dict]:
    """Try new lmarena-ai dataset first, fall back to lmsys/chatbot_arena_leaderboard."""
    try:
        result = await _fetch_lmarena_dataset()
        if result:
            log.info("Fetched arena ratings from lmarena-ai dataset: %d models", len(result))
            return result
    except Exception as e:
        log.debug("lmarena-ai dataset fetch failed (%s), trying lmsys fallback", e)
    return await _fetch_lmsys_dataset()


async def _fetch_lmarena_dataset() -> dict[str, dict]:
    """
    Fetch from lmarena-ai/leaderboard-dataset on HuggingFace.
    Expected columns: model_name, organization, rating (Elo), vote_count, rank, category.
    Dataset may have one row per (model, category) — we aggregate by model.
    """
    url = (
        "https://datasets-server.huggingface.co/rows"
        "?dataset=lmarena-ai%2Fleaderboard-dataset"
        "&config=default&split=train&offset=0&length=500"
    )
    async with httpx.AsyncClient(timeout=25) as client:
        r = await client.get(url)
        r.raise_for_status()

    rows_data = r.json().get("rows", [])
    if not rows_data:
        raise ValueError("Empty lmarena-ai dataset response")

    sample = rows_data[0].get("row", {})
    all_cols = list(sample.keys())

    model_col  = _pick_col(all_cols, ["model_name", "model", "key", "name"])
    rating_col = _pick_col(all_cols, ["rating", "Arena Score", "elo_rating", "score", "Arena Elo"])
    cat_col    = _pick_col(all_cols, ["category", "type", "task", "leaderboard"])

    if not model_col or not rating_col:
        raise ValueError(f"Unknown lmarena schema. Columns: {all_cols[:15]}")

    # Aggregate: for each model, collect best text Elo and vision Elo separately
    text_ratings: dict[str, float] = {}
    vision_ratings: dict[str, float] = {}

    for entry in rows_data:
        row = entry.get("row", {})
        model_id = str(row.get(model_col, "")).strip().lower()
        rating   = row.get(rating_col)
        category = str(row.get(cat_col, "")).lower() if cat_col else ""

        if not model_id or not isinstance(rating, (int, float)):
            continue

        if "vision" in category or "image" in category or "visual" in category:
            if model_id not in vision_ratings or rating > vision_ratings[model_id]:
                vision_ratings[model_id] = float(rating)
        else:
            if model_id not in text_ratings or rating > text_ratings[model_id]:
                text_ratings[model_id] = float(rating)

    if not text_ratings:
        raise ValueError("No usable text ratings in lmarena dataset")

    all_scores = list(text_ratings.values()) + list(vision_ratings.values())
    min_s, max_s = min(all_scores), max(all_scores)
    span = (max_s - min_s) or 1.0

    result: dict[str, dict] = {}
    for model_id in set(text_ratings) | set(vision_ratings):
        text_raw   = text_ratings.get(model_id, 0.0)
        vision_raw = vision_ratings.get(model_id, 0.0)

        text_stars   = _score_to_stars((text_raw - min_s) / span * 100)   if text_raw   else 0
        vision_stars = _score_to_stars((vision_raw - min_s) / span * 100) if vision_raw else 0
        elo = int(text_raw) if text_raw else (int(vision_raw) if vision_raw else None)

        result[model_id] = {"text": text_stars, "vision": vision_stars, "elo": elo}

    return result


async def _fetch_lmsys_dataset() -> dict[str, dict]:
    """
    Fetch from lmsys/chatbot_arena_leaderboard on HuggingFace.
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
        raise ValueError("Empty lmsys dataset response")

    sample_row = rows_data[0].get("row", {})
    all_cols = list(sample_row.keys())

    model_col  = _pick_col(all_cols, ["key", "model", "Model", "model_name", "name"])
    score_col  = _pick_col(all_cols, ["Arena Score", "Arena Elo", "Elo rating", "elo_rating", "rating"])
    vision_col = _pick_col(all_cols, ["Vision Arena Score", "Vision Elo", "vision_arena_score", "vision_score"])

    if not model_col or not score_col:
        raise ValueError(f"Unrecognised lmsys schema. Columns: {all_cols[:15]}")

    scores = [
        row["row"][score_col]
        for row in rows_data
        if isinstance(row["row"].get(score_col), (int, float))
    ]
    if not scores:
        raise ValueError("No numeric scores in lmsys dataset")

    min_s, max_s = min(scores), max(scores)
    span = (max_s - min_s) or 1.0

    result: dict[str, dict] = {}
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

        # raw score from Arena IS the Elo value (typically 1000-1700 range)
        result[model_id] = {"text": text_stars, "vision": vision_stars, "elo": int(raw)}

    return result


def _pick_col(cols: list[str], candidates: list[str]) -> Optional[str]:
    """Return first candidate that exists in cols (case-insensitive)."""
    cols_lower = {c.lower(): c for c in cols}
    for c in candidates:
        if c.lower() in cols_lower:
            return cols_lower[c.lower()]
    return None
