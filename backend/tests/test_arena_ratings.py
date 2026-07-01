"""Pins LM Arena rating fetch/aggregation logic — see docs/code-map.md
(services/arena_ratings.py).

`refresh_ratings()` pulls a public HuggingFace dataset (free, no API key) and
reshapes rows into per-model {text, vision, elo} star ratings. The reshaping
(column auto-detection across dataset schema variants, per-model max
aggregation, 0-100 → 0-5 star normalisation) and the hardcoded-fallback-on-error
behavior are the parts worth pinning. All HTTP calls are mocked (httpx.AsyncClient)
so these tests run offline.

Each test carries:
  Doc:  which documented area it protects
  Rule: the specific behavior it asserts
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import AppSettings
from app.services.arena_ratings import (
    SETTINGS_KEY,
    _fetch_from_huggingface,
    _fetch_lmarena_dataset,
    _fetch_lmsys_dataset,
    _hardcoded_stars,
    _pick_col,
    _score_to_stars,
    get_cached,
    refresh_ratings,
)


def _make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _mock_httpx_get(json_data: dict):
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    client = MagicMock()
    client.get = AsyncMock(return_value=resp)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=ctx)


# ── _score_to_stars ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("score,stars", [
    (95, 5), (92, 5), (91.9, 4), (82, 4), (81.9, 3),
    (70, 3), (69.9, 2), (55, 2), (54.9, 1), (0.1, 1), (0, 0),
])
def test_score_to_stars_thresholds(score, stars):
    # Doc:  services/arena_ratings.py — _score_to_stars
    # Rule: 0-100 quality score maps to 0-5 stars at the documented breakpoints.
    assert _score_to_stars(score) == stars


# ── _pick_col ────────────────────────────────────────────────────────────────────

def test_pick_col_returns_first_matching_candidate_case_insensitive():
    # Doc:  services/arena_ratings.py — _pick_col
    # Rule: matches a candidate name against actual columns case-insensitively,
    #       returning the column's original casing.
    assert _pick_col(["Model_Name", "Rating"], ["model_name", "model"]) == "Model_Name"


def test_pick_col_returns_none_when_nothing_matches():
    # Doc:  services/arena_ratings.py — _pick_col
    # Rule: no matching candidate → None (caller raises a schema error).
    assert _pick_col(["foo", "bar"], ["model_name", "model"]) is None


# ── _fetch_lmarena_dataset ────────────────────────────────────────────────────────

def test_fetch_lmarena_dataset_aggregates_best_score_per_model_and_category():
    # Doc:  services/arena_ratings.py — _fetch_lmarena_dataset
    # Rule: for each model, the highest text rating and highest vision rating are
    #       kept separately (rows are per model×category); scores are normalised
    #       to 0-100 across the whole dataset before star conversion.
    rows = {"rows": [
        {"row": {"model_name": "model-a", "rating": 1000, "category": "text"}},
        {"row": {"model_name": "model-a", "rating": 1300, "category": "text"}},
        {"row": {"model_name": "model-b", "rating": 1400, "category": "text"}},
        {"row": {"model_name": "model-a", "rating": 1100, "category": "vision arena"}},
    ]}
    with patch("httpx.AsyncClient", _mock_httpx_get(rows)):
        result = asyncio.run(_fetch_lmarena_dataset())

    assert result == {
        "model-a": {"text": 2, "vision": 0, "elo": 1300},
        "model-b": {"text": 5, "vision": 0, "elo": 1400},
    }


def test_fetch_lmarena_dataset_raises_on_empty_response():
    # Doc:  services/arena_ratings.py — _fetch_lmarena_dataset
    # Rule: an empty dataset response raises so the caller falls back to lmsys.
    with patch("httpx.AsyncClient", _mock_httpx_get({"rows": []})):
        with pytest.raises(ValueError):
            asyncio.run(_fetch_lmarena_dataset())


def test_fetch_lmarena_dataset_raises_on_unrecognised_schema():
    # Doc:  services/arena_ratings.py — _fetch_lmarena_dataset
    # Rule: if neither model nor rating column can be identified, raises rather
    #       than silently returning garbage ratings.
    rows = {"rows": [{"row": {"totally_unrelated_col": 1}}]}
    with patch("httpx.AsyncClient", _mock_httpx_get(rows)):
        with pytest.raises(ValueError):
            asyncio.run(_fetch_lmarena_dataset())


# ── _fetch_lmsys_dataset ──────────────────────────────────────────────────────────

def test_fetch_lmsys_dataset_normalises_scores_and_reads_vision_column():
    # Doc:  services/arena_ratings.py — _fetch_lmsys_dataset
    # Rule: text score comes from the Elo-like score column (raw value = elo);
    #       vision score is read from a separate vision column when present.
    rows = {"rows": [
        {"row": {"key": "model-a", "Arena Score": 1200, "Vision Arena Score": 1100}},
        {"row": {"key": "model-b", "Arena Score": 1400}},
    ]}
    with patch("httpx.AsyncClient", _mock_httpx_get(rows)):
        result = asyncio.run(_fetch_lmsys_dataset())

    assert result["model-a"]["elo"] == 1200
    assert result["model-b"]["elo"] == 1400
    assert result["model-b"]["vision"] == 0   # no vision column value for model-b


def test_fetch_lmsys_dataset_raises_when_no_numeric_scores():
    # Doc:  services/arena_ratings.py — _fetch_lmsys_dataset
    # Rule: rows with only non-numeric scores raise (no usable data).
    rows = {"rows": [{"row": {"key": "model-a", "Arena Score": "n/a"}}]}
    with patch("httpx.AsyncClient", _mock_httpx_get(rows)):
        with pytest.raises(ValueError):
            asyncio.run(_fetch_lmsys_dataset())


# ── _fetch_from_huggingface: fallback chain ───────────────────────────────────────

def test_fetch_from_huggingface_falls_back_to_lmsys_when_lmarena_fails():
    # Doc:  services/arena_ratings.py — _fetch_from_huggingface docstring
    # Rule: if the lmarena-ai dataset fetch fails, lmsys is tried next and its
    #       result is returned.
    lmsys_result = {"fallback-model": {"text": 3, "vision": 0, "elo": 1250}}
    with patch("app.services.arena_ratings._fetch_lmarena_dataset", new=AsyncMock(side_effect=ValueError("bad schema"))):
        with patch("app.services.arena_ratings._fetch_lmsys_dataset", new=AsyncMock(return_value=lmsys_result)):
            result = asyncio.run(_fetch_from_huggingface())
    assert result == lmsys_result


# ── refresh_ratings / get_cached ───────────────────────────────────────────────────

def test_refresh_ratings_merges_fetched_data_over_hardcoded():
    # Doc:  services/arena_ratings.py — refresh_ratings
    # Rule: fresh data is merged on top of the hardcoded table (so well-known
    #       models keep their fallback rating unless overridden by fresh data).
    db = _make_db()
    fresh = {"gpt-4o": {"text": 1, "vision": 1, "elo": 1}, "brand-new-model": {"text": 4, "vision": 0, "elo": 1300}}
    with patch("app.services.arena_ratings._fetch_from_huggingface", new=AsyncMock(return_value=fresh)):
        result = asyncio.run(refresh_ratings(db))

    assert result["gpt-4o"] == {"text": 1, "vision": 1, "elo": 1}       # overridden
    assert result["brand-new-model"] == fresh["brand-new-model"]        # new entry added
    assert "gemini-2.5-pro" in result                                   # untouched hardcoded entry survives
    db.close()


def test_refresh_ratings_falls_back_to_hardcoded_on_total_failure():
    # Doc:  services/arena_ratings.py — refresh_ratings docstring
    #       ("Falls back to hardcoded data on any error")
    # Rule: when the fetch raises, the hardcoded table is returned and persisted,
    #       not an empty/partial result.
    db = _make_db()
    with patch("app.services.arena_ratings._fetch_from_huggingface", new=AsyncMock(side_effect=RuntimeError("down"))):
        result = asyncio.run(refresh_ratings(db))

    assert result == _hardcoded_stars()
    row = db.query(AppSettings).filter(AppSettings.key == SETTINGS_KEY).first()
    assert json.loads(row.value) == _hardcoded_stars()
    db.close()


def test_get_cached_returns_hardcoded_when_no_row():
    # Doc:  services/arena_ratings.py — get_cached
    # Rule: with no cached AppSettings row, falls back to the hardcoded table.
    db = _make_db()
    assert get_cached(db) == _hardcoded_stars()
    db.close()


def test_get_cached_returns_persisted_row_when_present():
    # Doc:  services/arena_ratings.py — get_cached / refresh_ratings round trip
    # Rule: once refresh_ratings has persisted data, get_cached reads it back exactly.
    db = _make_db()
    with patch("app.services.arena_ratings._fetch_from_huggingface", new=AsyncMock(return_value={"m": {"text": 2, "vision": 0, "elo": 900}})):
        asyncio.run(refresh_ratings(db))
    cached = get_cached(db)
    assert cached["m"] == {"text": 2, "vision": 0, "elo": 900}
    db.close()
