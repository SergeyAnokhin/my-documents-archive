"""Pins AI-analysis output parsing — see docs/code-map.md (services/ai_analysis.py).

`_parse_result` turns raw LLM text into an `AnalysisResult`. The non-trivial rules
worth pinning: tolerate markdown code fences, coerce field types, and normalise
empty/absent fields to None / documented defaults.

Each test carries:
  Doc:  which documented area it protects (or "none" for code-only behavior)
  Rule: the specific behavior it asserts
"""
import pytest

from app.services.ai_analysis import _parse_result


def test_parse_result_strips_json_code_fence():
    # Doc:  none in prose docs — pins the `_parse_result` docstring ("tolerating
    #       markdown code fences"). ai_analysis.py is documented at docs/code-map.md,
    #       but fence-stripping is a robustness detail in the function itself.
    # Rule: a ```json … ``` fence is stripped before JSON parsing.
    raw = '```json\n{"summary": "hello", "document_type": "invoice"}\n```'
    r = _parse_result(raw)
    assert r.summary == "hello"
    assert r.document_type == "invoice"


def test_parse_result_coerces_types():
    # Doc:  docs/code-map.md → services/ai_analysis.py lists the output fields
    #       (summary, document_type +confidence, tags, amount). No prose rule on
    #       coercion itself — this guards against an LLM returning loose JSON types.
    # Rule: summary→str, confidence→float, every tag→str, amount→float.
    raw = (
        '{"summary": 42, "document_type_confidence": "0.8", '
        '"tags": ["a", 7], "amount": "150.5"}'
    )
    r = _parse_result(raw)
    assert r.summary == "42"                 # str() coercion
    assert r.document_type_confidence == 0.8  # float() coercion
    assert r.tags == ["a", "7"]              # every tag stringified
    assert r.amount == 150.5                 # float() coercion


def test_parse_result_normalises_empty_and_absent_fields_to_none():
    # Doc:  docs/code-map.md / ANALYSIS_SYSTEM prompt — optional fields are
    #       "<value> or null if absent" (organization, amount, currency, person…).
    # Rule: empty string and JSON null both normalise to Python None.
    r = _parse_result('{"organization": "", "amount": null}')
    assert r.organization is None   # "" → None
    assert r.amount is None          # null stays None
    assert r.amount_currency is None
    assert r.person_first_name is None


def test_parse_result_applies_documented_defaults():
    # Doc:  docs/code-map.md §Gotchas ("unclassified vs other") and the
    #       ANALYSIS_SYSTEM prompt ("Use 'unclassified' if it does not fit").
    # Rule: missing document_type → "unclassified", missing confidence → 0.0.
    r = _parse_result("{}")
    assert r.document_type == "unclassified"
    assert r.document_type_confidence == 0.0
    assert r.summary == ""
    assert r.tags == []


def test_parse_result_raises_on_non_json():
    # Doc:  none — general test. `analyze_document()` relies on a parse failure
    #       raising so it can fail over to the next provider (see its try/except).
    # Rule: non-JSON input raises (json.JSONDecodeError ⊂ ValueError).
    with pytest.raises(ValueError):
        _parse_result("not json at all")
