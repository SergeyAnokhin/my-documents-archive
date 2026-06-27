"""Pins how analysis metadata is written onto a Document — see docs/code-map.md (indexer.py).

`_apply_analysis_result` is the single helper shared by Step 3 (vision-as-analysis)
and Step 4 (text analysis); both call it so the two paths populate identical columns.
"""
from datetime import datetime

from app.models import Document
from app.services.ai_analysis import AnalysisResult
from app.services.indexer import _apply_analysis_result, _is_unclassified


def test_apply_analysis_result_writes_all_metadata_columns():
    # Rule: every AnalysisResult content field lands on the matching Document column,
    # source is marked "auto", and a valid YYYY-MM-DD date is parsed to a datetime.
    doc = Document(filename="x.pdf", filepath="/x.pdf", source="sync")
    result = AnalysisResult(
        summary="a summary",
        document_type="invoice",
        document_type_confidence=0.9,
        tags=["a", "b"],
        language="en",
        organization="ACME",
        amount=150.5,
        amount_currency="EUR",
        person_first_name="John",
        person_last_name="Doe",
        document_date="2024-03-15",
    )
    _apply_analysis_result(doc, result, db=None)

    assert doc.document_type == "invoice"
    assert doc.classification_confidence == 0.9
    assert doc.classification_source == "auto"
    assert doc.tags == ["a", "b"]
    assert doc.organization == "ACME"
    assert doc.amount == 150.5
    assert doc.document_date == datetime(2024, 3, 15)


def test_apply_analysis_result_ignores_invalid_date():
    # Rule: a malformed document_date is silently dropped (column stays unset),
    # never raises — a bad LLM date must not break indexing.
    doc = Document(filename="x.pdf", filepath="/x.pdf", source="sync")
    result = AnalysisResult(document_type="letter", document_date="not-a-date")
    _apply_analysis_result(doc, result, db=None)

    assert doc.document_type == "letter"
    assert doc.document_date is None


def test_is_unclassified_predicate():
    # Rule (bug fix): reclassify_unclassified_batch only counts a doc as
    # "classified" when its type is a real category. None / "unclassified" /
    # "other" all mean still-unclassified — these are the three values the
    # "classify unclassified" job retries and the stats counter keys on.
    assert _is_unclassified(Document(filename="a", filepath="/a", document_type=None))
    assert _is_unclassified(Document(filename="a", filepath="/a", document_type="unclassified"))
    assert _is_unclassified(Document(filename="a", filepath="/a", document_type="other"))
    assert not _is_unclassified(Document(filename="a", filepath="/a", document_type="invoice"))
