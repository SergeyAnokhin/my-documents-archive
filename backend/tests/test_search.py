"""Pins documented search rules — see docs/api.md (Search) and docs/architecture.md.

The hybrid merge order (both-sets → semantic-only → fulltext-only) is the
non-obvious rule worth pinning.
"""
from app.routers.search import _highlight, _merge_hybrid


def test_highlight_wraps_match_with_ellipsis():
    text = "x" * 100 + "INVOICE" + "y" * 200
    out = _highlight(text, "invoice")
    assert "INVOICE" in out
    assert out.startswith("…") and out.endswith("…")


def test_highlight_no_match_returns_prefix():
    assert _highlight("hello world", "zzz") == "hello world"
    assert _highlight(None, "q") is None


def test_merge_hybrid_orders_both_then_semantic_then_fulltext():
    result = _merge_hybrid([1, 2, 3], {3, 4, 5})
    # Tier 1 (in both): [3]; Tier 2 (semantic only): [1, 2]; Tier 3 (fulltext only): {4, 5}
    assert result[:3] == [3, 1, 2]
    assert set(result[3:]) == {4, 5}
    assert len(result) == 5
