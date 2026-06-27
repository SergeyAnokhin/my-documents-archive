"""Pins icon-suggestion logic — see docs/code-map.md (services/type_icon_suggestion.py).

All LLM calls are mocked so these tests run offline with no API cost.
Async functions are exercised via asyncio.run() (no extra test dependencies needed).

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
from app.services.type_icon_suggestion import (
    ALLOWED_ICONS,
    STATIC_ICON_VALUES,
    _suggest_one,
    _save_custom_type_icons,
    get_custom_type_icons,
    get_pending_custom_types,
    suggest_icons_for_types,
)


# ── helpers ────────────────────────────────────────────────────────────────────

def _make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _make_provider(name: str = "mock") -> MagicMock:
    p = MagicMock()
    p.name = name
    p.provider_type = "openai"
    return p


def _icon_resp(icon_name: str) -> tuple:
    return (json.dumps({"icon": icon_name}), 10, 5, 0.0)


# ── _suggest_one ───────────────────────────────────────────────────────────────

def test_suggest_one_accepts_valid_icon():
    # Doc:  services/type_icon_suggestion.py — _suggest_one
    # Rule: when LLM returns a valid, non-taken icon it is returned immediately.
    with patch(
        "app.services.type_icon_suggestion.run_text",
        new=AsyncMock(return_value=_icon_resp("Briefcase")),
    ):
        result = asyncio.run(
            _suggest_one("work_order", taken=set(STATIC_ICON_VALUES), providers=[_make_provider()])
        )
    assert result == "Briefcase"


def test_suggest_one_retries_on_conflict():
    # Doc:  services/type_icon_suggestion.py — _suggest_one
    # Rule: if LLM returns an icon already in `taken`, it adds it to `excluded`
    #       and retries; the second attempt with a free icon succeeds.
    call_count = {"n": 0}

    async def mock_run(provider, system, user_msg):
        call_count["n"] += 1
        icon = "Building" if call_count["n"] == 1 else "Truck"
        return _icon_resp(icon)

    taken = set(STATIC_ICON_VALUES) | {"Building"}
    with patch("app.services.type_icon_suggestion.run_text", new=mock_run):
        result = asyncio.run(
            _suggest_one("logistics", taken=taken, providers=[_make_provider()])
        )

    assert result == "Truck"
    assert call_count["n"] == 2


def test_suggest_one_retries_on_unknown_icon():
    # Doc:  services/type_icon_suggestion.py — _suggest_one
    # Rule: an icon name not in ALLOWED_ICONS is treated as invalid; the attempt
    #       retries with that name added to excluded.
    call_count = {"n": 0}

    async def mock_run(provider, system, user_msg):
        call_count["n"] += 1
        icon = "FakeIconThatDoesNotExist" if call_count["n"] == 1 else "Globe"
        return _icon_resp(icon)

    with patch("app.services.type_icon_suggestion.run_text", new=mock_run):
        result = asyncio.run(
            _suggest_one("intl_doc", taken=set(STATIC_ICON_VALUES), providers=[_make_provider()])
        )

    assert result == "Globe"
    assert call_count["n"] == 2


def test_suggest_one_returns_none_when_retries_exhausted():
    # Doc:  services/type_icon_suggestion.py — _suggest_one
    # Rule: when all max_retries attempts return conflicting icons, None is returned
    #       (frontend falls back to FileText).
    with patch(
        "app.services.type_icon_suggestion.run_text",
        new=AsyncMock(return_value=_icon_resp("Briefcase")),
    ):
        taken = set(ALLOWED_ICONS)  # every icon is already taken
        result = asyncio.run(
            _suggest_one("my_type", taken=taken, providers=[_make_provider()], max_retries=5)
        )
    assert result is None


def test_suggest_one_returns_none_when_no_icons_available():
    # Doc:  services/type_icon_suggestion.py — _suggest_one
    # Rule: if excluded set already covers all ALLOWED_ICONS, None is returned
    #       without calling the LLM at all.
    with patch(
        "app.services.type_icon_suggestion.run_text",
        new=AsyncMock(return_value=_icon_resp("Globe")),
    ) as mock_run:
        taken = set(ALLOWED_ICONS)
        result = asyncio.run(
            _suggest_one("overflow_type", taken=taken, providers=[_make_provider()])
        )
    assert result is None
    mock_run.assert_not_called()


def test_suggest_one_excluded_list_grows_on_conflict():
    # Doc:  services/type_icon_suggestion.py — _suggest_one
    # Rule: each conflicting icon is appended to the EXCLUDED list in the next
    #       attempt's user_msg so the LLM isn't given the same bad option again.
    captured_msgs: list[str] = []

    async def mock_run(provider, system, user_msg):
        captured_msgs.append(user_msg)
        if len(captured_msgs) == 1:
            return _icon_resp("Building")   # first attempt: conflicts
        return _icon_resp("Truck")          # second attempt: accepted

    taken = set(STATIC_ICON_VALUES) | {"Building"}
    with patch("app.services.type_icon_suggestion.run_text", new=mock_run):
        asyncio.run(_suggest_one("cargo", taken=taken, providers=[_make_provider()]))

    assert len(captured_msgs) == 2
    # The second attempt's message must list Building in EXCLUDED
    assert "Building" in captured_msgs[1]


# ── suggest_icons_for_types ────────────────────────────────────────────────────

def test_suggest_icons_for_types_skips_already_assigned():
    # Doc:  services/type_icon_suggestion.py — suggest_icons_for_types
    # Rule: types already in custom_type_icons are not sent to the LLM.
    db = _make_db()
    _save_custom_type_icons({"existing_type": "Globe"}, db)

    with patch("app.services.type_icon_suggestion._get_providers", return_value=[_make_provider()]):
        with patch("app.services.type_icon_suggestion.run_text", new=AsyncMock()) as mock_run:
            result = asyncio.run(suggest_icons_for_types(["existing_type"], db))

    assert result == {}
    mock_run.assert_not_called()
    db.close()


def test_suggest_icons_for_types_returns_empty_without_providers():
    # Doc:  services/type_icon_suggestion.py — suggest_icons_for_types
    # Rule: if no AI providers are configured, returns {} without error.
    db = _make_db()
    with patch("app.services.type_icon_suggestion._get_providers", return_value=[]):
        result = asyncio.run(suggest_icons_for_types(["custom_type"], db))
    assert result == {}
    db.close()


def test_suggest_icons_for_types_builds_taken_set_across_batch():
    # Doc:  services/type_icon_suggestion.py — suggest_icons_for_types
    # Rule: once type_a is assigned icon X, X appears in the EXCLUDED list
    #       of type_b's LLM call so the two types never share an icon.
    db = _make_db()
    captured_msgs: list[str] = []

    async def mock_run(provider, system, user_msg):
        captured_msgs.append(user_msg)
        return _icon_resp("Briefcase") if len(captured_msgs) == 1 else _icon_resp("Package")

    with patch("app.services.type_icon_suggestion._get_providers", return_value=[_make_provider()]):
        with patch("app.services.type_icon_suggestion.run_text", new=mock_run):
            result = asyncio.run(suggest_icons_for_types(["type_a", "type_b"], db))

    assert result["type_a"] == "Briefcase"
    assert result["type_b"] == "Package"
    # type_b's user_msg must list Briefcase in EXCLUDED
    assert "Briefcase" in captured_msgs[1]
    db.close()


def test_suggest_icons_for_types_persists_to_db():
    # Doc:  services/type_icon_suggestion.py — suggest_icons_for_types
    # Rule: newly assigned icons are written to AppSettings so they survive restart.
    db = _make_db()

    with patch("app.services.type_icon_suggestion._get_providers", return_value=[_make_provider()]):
        with patch(
            "app.services.type_icon_suggestion.run_text",
            new=AsyncMock(return_value=_icon_resp("Archive")),
        ):
            asyncio.run(suggest_icons_for_types(["work_doc"], db))

    reloaded = get_custom_type_icons(db)
    assert reloaded.get("work_doc") == "Archive"
    db.close()


# ── get_custom_type_icons / _save_custom_type_icons ───────────────────────────

def test_get_custom_type_icons_empty_when_no_row():
    # Doc:  services/type_icon_suggestion.py
    # Rule: returns {} when AppSettings has no custom_type_icons row.
    db = _make_db()
    assert get_custom_type_icons(db) == {}
    db.close()


def test_save_and_reload_icons():
    # Doc:  services/type_icon_suggestion.py
    # Rule: _save persists icons; get_custom_type_icons reads them back exactly.
    db = _make_db()
    icons = {"work_order": "Briefcase", "field_report": "MapPin"}
    _save_custom_type_icons(icons, db)
    assert get_custom_type_icons(db) == icons
    db.close()


def test_save_icons_upserts_row():
    # Doc:  services/type_icon_suggestion.py
    # Rule: a second save with different data overwrites the first (upsert).
    db = _make_db()
    _save_custom_type_icons({"a": "Globe"}, db)
    _save_custom_type_icons({"a": "Globe", "b": "Truck"}, db)
    assert get_custom_type_icons(db) == {"a": "Globe", "b": "Truck"}
    db.close()


# ── get_pending_custom_types ──────────────────────────────────────────────────

def test_get_pending_custom_types_excludes_built_in_and_assigned():
    # Doc:  services/type_icon_suggestion.py — get_pending_custom_types
    # Rule: returns only types that are (a) not in the built-in taxonomy and
    #       (b) not yet assigned a custom icon.
    from app.models import Document as DocModel

    db = _make_db()
    db.add(DocModel(
        filename="a.pdf", filepath="/a.pdf",
        document_type="invoice",        # built-in, must be excluded
        ocr_status="done", vision_status="done", analysis_status="done",
    ))
    db.add(DocModel(
        filename="b.pdf", filepath="/b.pdf",
        document_type="work_order",     # custom, no icon yet → must appear
        ocr_status="done", vision_status="done", analysis_status="done",
    ))
    db.add(DocModel(
        filename="c.pdf", filepath="/c.pdf",
        document_type="field_report",   # custom, already has an icon → excluded
        ocr_status="done", vision_status="done", analysis_status="done",
    ))
    db.commit()
    _save_custom_type_icons({"field_report": "MapPin"}, db)

    pending = get_pending_custom_types(db)

    assert "work_order" in pending
    assert "invoice" not in pending
    assert "field_report" not in pending
    db.close()
