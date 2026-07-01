"""Pins the cluster-based recategorization pipeline — see docs/code-map.md
(services/recluster.py) and docs/recluster.md.

`run_recluster()` embeds document summaries locally (free), auto-selects a
cluster count via silhouette score, then asks an LLM to name each cluster —
this is the one paid step, and it's a conflict-aware retry loop (each cluster
must not reuse an icon taken by an earlier one in the same run). These tests
mock `run_text` (like test_type_icon_suggestion.py) so the retry/prompt logic
is pinned without any real, billable call. The pure-logic helpers (summary
cleaning, k-range bounds, type/tag application, icon+name persistence) are
tested directly.

Each test carries:
  Doc:  which documented area it protects
  Rule: the specific behavior it asserts
"""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.services.recluster import (
    _apply_new_type,
    _k_range,
    _name_cluster,
    _save_cluster_data,
    _strip_for_clustering,
)
from app.services.type_icon_suggestion import ALLOWED_ICONS, STATIC_ICON_VALUES, get_custom_type_icons


def _make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _make_provider() -> MagicMock:
    p = MagicMock()
    p.name = "mock"
    p.provider_type = "openai"
    return p


def _icon_resp(slug: str, icon: str, name_en="En", name_fr="Fr", name_ru="Ru") -> tuple:
    payload = json.dumps({"slug": slug, "icon": icon, "name_en": name_en, "name_fr": name_fr, "name_ru": name_ru})
    return (payload, 10, 5, 0.0)


# ── _strip_for_clustering ────────────────────────────────────────────────────────

def test_strip_for_clustering_removes_dates_names_and_tags():
    # Doc:  docs/recluster.md — summary cleaning step
    # Rule: dates, the document's person/org names, and its own tags are
    #       stripped out so clustering groups by topic, not by who/when.
    summary = (
        "Invoice from Acme Corp dated 15 janvier 2024 for John Smith regarding "
        "office supplies and equipment rental services this quarter"
    )
    cleaned = _strip_for_clustering(
        summary, tags=["invoice", "equipment"], person_first="John", person_last="Smith", organization="Acme Corp",
    )
    assert "Acme Corp" not in cleaned
    assert "John" not in cleaned and "Smith" not in cleaned
    assert "2024" not in cleaned
    assert "  " not in cleaned  # whitespace collapsed to single spaces


def test_strip_for_clustering_falls_back_to_original_when_too_short():
    # Doc:  docs/recluster.md — summary cleaning step
    # Rule: if stripping leaves fewer than 20 characters, the original summary
    #       is used instead (an empty/near-empty embedding input is useless).
    summary = "Report by Jane Doe, 2023."
    cleaned = _strip_for_clustering(summary, tags=[], person_first="Jane", person_last="Doe", organization=None)
    assert cleaned == summary


# ── _k_range ─────────────────────────────────────────────────────────────────────

def test_k_range_uses_min_clusters_floor_for_small_document_counts():
    # Doc:  docs/recluster.md — auto k-selection
    # Rule: for a small document count, k_min falls back to the min_clusters floor.
    k_min, k_max = _k_range(n=10, max_clusters=40, min_clusters=2)
    assert k_min == 2
    assert k_max >= k_min


def test_k_range_respects_custom_min_clusters_floor():
    # Doc:  docs/recluster.md — min_clusters configuration
    # Rule: a caller-supplied min_clusters raises k_min even when sqrt(n/20)
    #       would suggest fewer clusters.
    k_min, _ = _k_range(n=10, max_clusters=40, min_clusters=6)
    assert k_min == 6


def test_k_range_caps_at_max_clusters():
    # Doc:  docs/recluster.md — max_clusters configuration
    # Rule: k_max never exceeds the configured max_clusters cap, even for a
    #       huge document count.
    _, k_max = _k_range(n=100_000, max_clusters=15, min_clusters=2)
    assert k_max == 15


def test_k_range_scales_up_with_more_documents():
    # Doc:  docs/recluster.md — auto k-selection
    # Rule: a larger document count produces a wider (or equal) [k_min, k_max]
    #       range than a smaller one.
    small = _k_range(n=100, max_clusters=40, min_clusters=2)
    large = _k_range(n=5000, max_clusters=40, min_clusters=2)
    assert large[1] >= small[1]


# ── _apply_new_type ───────────────────────────────────────────────────────────────

def test_apply_new_type_preserves_meaningful_old_type_in_tags():
    # Doc:  docs/recluster.md — apply step
    # Rule: when a meaningful old type changes, it's preserved as a tag.
    doc = SimpleNamespace(document_type="invoice", tags=["urgent"], classification_source=None, manually_classified=True)
    _apply_new_type(doc, "tax_document")
    assert doc.document_type == "tax_document"
    assert "invoice" in doc.tags
    assert doc.classification_source == "auto"
    assert doc.manually_classified is False


def test_apply_new_type_does_not_preserve_unclassified_or_other():
    # Doc:  docs/recluster.md — apply step
    # Rule: "unclassified"/"other" are not meaningful — never added to tags.
    doc = SimpleNamespace(document_type="unclassified", tags=[], classification_source=None, manually_classified=False)
    _apply_new_type(doc, "invoice")
    assert doc.tags == []
    assert doc.document_type == "invoice"


def test_apply_new_type_skips_tag_when_type_unchanged():
    # Doc:  docs/recluster.md — apply step
    # Rule: if the new type equals the old type, nothing is added to tags.
    doc = SimpleNamespace(document_type="invoice", tags=[], classification_source=None, manually_classified=False)
    _apply_new_type(doc, "invoice")
    assert doc.tags == []


# ── _save_cluster_data ────────────────────────────────────────────────────────────

def test_save_cluster_data_skips_builtin_and_unclassified_slugs():
    # Doc:  docs/recluster.md — persistence step
    # Rule: built-in taxonomy slugs and "unclassified" never get a custom
    #       icon/name entry (they already have hardcoded ones).
    db = _make_db()
    cluster_names = {
        0: ("invoice", "Receipt", "Invoice", "Facture", "Счёт"),   # built-in slug
        1: ("unclassified", "FileText", "Unclassified", "Non classifié", "Без категории"),
        2: ("field_report", "MapPin", "Field Report", "Rapport de terrain", "Отчёт с места"),
    }
    _save_cluster_data(cluster_names, db)

    icons = get_custom_type_icons(db)
    assert icons == {"field_report": "MapPin"}
    db.close()


def test_save_cluster_data_merges_with_existing_entries():
    # Doc:  docs/recluster.md — persistence step
    # Rule: a later recluster run merges new slugs in without dropping ones
    #       from an earlier run (upsert, not overwrite).
    db = _make_db()
    _save_cluster_data({0: ("type_a", "Globe", "A", "A", "A")}, db)
    _save_cluster_data({0: ("type_b", "Truck", "B", "B", "B")}, db)

    icons = get_custom_type_icons(db)
    assert icons == {"type_a": "Globe", "type_b": "Truck"}
    db.close()


# ── _name_cluster ──────────────────────────────────────────────────────────────────

def test_name_cluster_prompt_lists_available_and_excludes_taken_icons():
    # Doc:  docs/recluster.md — LLM naming step
    # Rule: taken icons appear in the EXCLUDED section and are absent from
    #       AVAILABLE, so the LLM can't repeat an icon used by an earlier cluster.
    captured = {}

    async def mock_run(provider, system, user_msg):
        captured["user_msg"] = user_msg
        return _icon_resp("cargo_manifest", "Truck")

    taken = set(STATIC_ICON_VALUES) | {"Globe"}
    with patch("app.services.ai_analysis.run_text", new=mock_run):
        asyncio.run(_name_cluster(["a shipment summary"], taken, db=None, provider=_make_provider()))

    assert "Globe" in captured["user_msg"].split("EXCLUDED:")[1]
    assert "Truck" in captured["user_msg"].split("AVAILABLE:")[1].split("EXCLUDED:")[0]


def test_name_cluster_accepts_valid_non_conflicting_icon():
    # Doc:  docs/recluster.md — LLM naming step
    # Rule: a valid icon not in taken_icons is accepted on the first attempt.
    with patch("app.services.ai_analysis.run_text", new=AsyncMock(return_value=_icon_resp("cargo", "Truck", "Cargo", "Cargaison", "Груз"))):
        result = asyncio.run(_name_cluster(["s"], set(STATIC_ICON_VALUES), db=None, provider=_make_provider()))
    assert result == ("cargo", "Truck", "Cargo", "Cargaison", "Груз")


def test_name_cluster_retries_on_unknown_icon_name():
    # Doc:  docs/recluster.md — LLM naming step
    # Rule: an icon not in ALLOWED_ICONS is rejected and retried with that name excluded.
    calls = {"n": 0}

    async def mock_run(provider, system, user_msg):
        calls["n"] += 1
        icon = "TotallyNotARealIcon" if calls["n"] == 1 else "Truck"
        return _icon_resp("cargo", icon)

    with patch("app.services.ai_analysis.run_text", new=mock_run):
        result = asyncio.run(_name_cluster(["s"], set(STATIC_ICON_VALUES), db=None, provider=_make_provider()))

    assert result[1] == "Truck"
    assert calls["n"] == 2


def test_name_cluster_retries_on_icon_conflicting_with_earlier_cluster():
    # Doc:  docs/recluster.md — LLM naming step (conflict-aware retry)
    # Rule: an icon already in taken_icons is rejected and retried.
    calls = {"n": 0}

    async def mock_run(provider, system, user_msg):
        calls["n"] += 1
        icon = "Globe" if calls["n"] == 1 else "Truck"
        return _icon_resp("cargo", icon)

    taken = set(STATIC_ICON_VALUES) | {"Globe"}
    with patch("app.services.ai_analysis.run_text", new=mock_run):
        result = asyncio.run(_name_cluster(["s"], taken, db=None, provider=_make_provider()))

    assert result[1] == "Truck"
    assert calls["n"] == 2


def test_name_cluster_returns_fallback_after_max_retries_exhausted():
    # Doc:  docs/recluster.md — LLM naming step
    # Rule: if every attempt returns a conflicting icon, the documented
    #       "unclassified"/FileText fallback is returned instead of failing the run.
    with patch("app.services.ai_analysis.run_text", new=AsyncMock(return_value=_icon_resp("cargo", "Globe"))):
        taken = set(STATIC_ICON_VALUES) | {"Globe"}
        result = asyncio.run(_name_cluster(["s"], taken, db=None, provider=_make_provider(), max_retries=3))

    assert result == ("unclassified", "FileText", "Unclassified", "Non classifié", "Без категории")


def test_name_cluster_returns_fallback_without_calling_llm_when_no_icons_left():
    # Doc:  docs/recluster.md — LLM naming step
    # Rule: if taken_icons already covers every ALLOWED_ICONS entry, the
    #       fallback is returned without spending an LLM call.
    with patch("app.services.ai_analysis.run_text", new=AsyncMock(return_value=_icon_resp("x", "Globe"))) as mock_run:
        result = asyncio.run(_name_cluster(["s"], set(ALLOWED_ICONS), db=None, provider=_make_provider()))

    assert result == ("unclassified", "FileText", "Unclassified", "Non classifié", "Без категории")
    mock_run.assert_not_called()
