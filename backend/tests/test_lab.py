"""Pins lab judge-output parsing — see docs/lab-mode.md.

The judge model may wrap its JSON in markdown fences; _parse_json must tolerate
that, mirroring ai_analysis._parse_result.
"""
import json

import pytest

from app.services.lab import _parse_json, JUDGE_SYSTEM, OCR_VISION_PROMPT


def test_parse_json_plain():
    out = _parse_json('{"best": "tesseract", "rankings": []}')
    assert out["best"] == "tesseract"


def test_parse_json_tolerates_markdown_fences():
    raw = "```json\n" + json.dumps({"best": "AI", "summary": "ok"}) + "\n```"
    out = _parse_json(raw)
    assert out["best"] == "AI"
    assert out["summary"] == "ok"


def test_parse_json_raises_on_garbage():
    with pytest.raises(json.JSONDecodeError):
        _parse_json("not json at all")


def test_prompts_request_verbatim_and_json():
    # Vision prompt must ask for transcription, not description.
    assert "Transcribe" in OCR_VISION_PROMPT
    # Judge must be instructed to return JSON with the agreed keys.
    assert "rankings" in JUDGE_SYSTEM and "best" in JUDGE_SYSTEM
