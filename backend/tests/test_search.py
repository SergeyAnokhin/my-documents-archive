"""Pins documented search rules — see docs/api.md (Search) and docs/architecture.md.

The hybrid merge order (both-sets → semantic-only → fulltext-only) is the
non-obvious rule worth pinning, along with quoted-phrase parsing and the
cross-script (Cyrillic↔Latin) name-matching expansion.

Each test below carries:
  Doc:  which documented area it protects (or "none" for code-only behavior)
  Rule: the specific behavior it asserts
"""
from app.routers.search import (
    _expand_fulltext_query,
    _highlight,
    _merge_hybrid,
    _parse_query,
    _transliterate_cyr_to_lat,
)


def test_highlight_wraps_match_with_ellipsis():
    # Doc:  docs/api.md §Search — the `SearchResult.highlight?` field.
    # Rule: a hit yields a ~200-char snippet around the first match, ellipsis-wrapped
    #       when truncated. The exact ±80/+120 window is the `_highlight` docstring,
    #       not a prose-doc rule.
    text = "x" * 100 + "INVOICE" + "y" * 200
    out = _highlight(text, "invoice")
    assert "INVOICE" in out
    assert out.startswith("…") and out.endswith("…")


def test_highlight_no_match_returns_prefix():
    # Doc:  docs/api.md §Search — the `SearchResult.highlight?` field.
    # Rule: no match → first 200 chars unwrapped; None text → None (no highlight).
    #       Code-docstring behavior, no prose-doc requirement on the fallback.
    assert _highlight("hello world", "zzz") == "hello world"
    assert _highlight(None, "q") is None


def test_merge_hybrid_orders_both_then_semantic_then_fulltext():
    # Doc:  docs/api.md §Search — `hybrid` mode (Phase 4).
    # Rule: tier order is both-sets → semantic-only → fulltext-only. The ordering
    #       itself lives in the `_merge_hybrid` docstring, not in prose docs.
    result = _merge_hybrid([1, 2, 3], {3, 4, 5})
    # Tier 1 (in both): [3]; Tier 2 (semantic only): [1, 2]; Tier 3 (fulltext only): {4, 5}
    assert result[:3] == [3, 1, 2]
    assert set(result[3:]) == {4, 5}
    assert len(result) == 5


def test_merge_hybrid_preserves_semantic_rank_and_dedupes():
    # Doc:  docs/api.md §Search — `hybrid` mode (Phase 4).
    # Rule: an id present in both sets is emitted once, in tier 1, and semantic rank
    #       order is preserved. Invariant of `_merge_hybrid`; no prose-doc rule.
    result = _merge_hybrid([5, 9, 5], {9})
    assert result == [9, 5]  # 9 in both → first; 5 semantic-only; duplicate 5 dropped


# ── Quoted-phrase parsing ───────────────────────────────────────────────────────

def test_parse_query_splits_quoted_phrases_from_words():
    # Doc:  none in prose docs — pins the `_parse_query` docstring example. (Fulltext
    #       search itself is documented at docs/code-map.md → routers/search.py, but
    #       quoted-phrase handling is described only in the function's own docstring.)
    # Rule: `"..."` chunks become exact phrases; the rest split into words.
    phrases, words = _parse_query('договор "Иванов Иван" 2024')
    assert phrases == ["Иванов Иван"]
    assert words == ["договор", "2024"]


def test_parse_query_no_quotes_returns_all_words():
    # Doc:  none in prose docs — pins `_parse_query` (see above).
    # Rule: with no quotes, every whitespace-separated token is a word; no phrases.
    phrases, words = _parse_query("invoice 2023 acme")
    assert phrases == []
    assert words == ["invoice", "2023", "acme"]


# ── Cross-script name matching ──────────────────────────────────────────────────
# NOTE: cross-script (Cyrillic↔Latin) name search is NOT described in any prose doc
# under docs/ — it exists only in the `search.py` helper docstrings. These are
# therefore general tests that pin current code behavior, not a documented contract.
# (Candidate to document under docs/api.md §Search if it becomes a relied-on feature.)

def test_transliterate_cyrillic_to_latin():
    # Doc:  none — general test pinning `_transliterate_cyr_to_lat`.
    # Rule: per-char Cyrillic→Latin map, lower-cased (Сергей → sergey).
    assert _transliterate_cyr_to_lat("Сергей") == "sergey"
    assert _transliterate_cyr_to_lat("Шевченко") == "shevchenko"


def test_expand_query_adds_cyrillic_variant_for_latin_name():
    # Doc:  none — general test pinning `_expand_fulltext_query`.
    # Rule: a known Latin first name expands to its Cyrillic spelling variant.
    variants = _expand_fulltext_query("ivan")
    assert variants == ["ivan", "иван"]


def test_expand_query_adds_latin_variant_for_cyrillic_name():
    # Doc:  none — general test pinning `_expand_fulltext_query`.
    # Rule: a Cyrillic word expands to its transliterated Latin variant.
    variants = _expand_fulltext_query("сергей")
    assert variants == ["сергей", "sergey"]


def test_expand_query_no_variant_when_unchanged():
    # Doc:  none — general test pinning `_expand_fulltext_query`.
    # Rule: pure-ASCII with no name-map hit → only the original (no duplicate variant).
    assert _expand_fulltext_query("invoice") == ["invoice"]
