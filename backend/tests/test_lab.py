"""Pins lab judge-output parsing — see docs/lab-mode.md.

The judge model may wrap its JSON in markdown fences; _parse_json must tolerate
that, mirroring ai_analysis._parse_result.
"""
import json

import pytest

from app.services.lab import _parse_json, _judge_system, VISION_ANALYSIS_PROMPT, _parse_vision_analysis


def test_parse_json_plain():
    out = _parse_json('{"best": "tesseract", "rankings": []}')
    assert out["best"] == "tesseract"


def test_parse_json_tolerates_markdown_fences():
    raw = "```json\n" + json.dumps({"best": "AI", "summary": "ok"}) + "\n```"
    out = _parse_json(raw)
    assert out["best"] == "AI"
    assert out["summary"] == "ok"


def test_parse_json_raises_on_garbage():
    with pytest.raises((json.JSONDecodeError, ValueError)):
        _parse_json("not json at all")


def test_prompts_request_verbatim_and_json():
    # Vision prompt must ask for transcription and return JSON with text + fields.
    assert "text" in VISION_ANALYSIS_PROMPT
    assert "fields" in VISION_ANALYSIS_PROMPT
    assert "JSON" in VISION_ANALYSIS_PROMPT
    # Judge prompts (with and without image) must include the agreed JSON keys.
    for with_image in (True, False):
        prompt = _judge_system(with_image)
        assert "rankings" in prompt and "best" in prompt


def test_judge_prompt_language():
    # Russian language instruction must appear in the prompt.
    prompt_ru = _judge_system(with_image=False, language="ru")
    assert "Russian" in prompt_ru
    # English is the default.
    prompt_en = _judge_system(with_image=True)
    assert "English" in prompt_en


def test_parse_vision_analysis_json():
    raw = '{"text": "Hello world", "fields": {"document_type": "invoice", "language": "en"}}'
    text, fields = _parse_vision_analysis(raw)
    assert text == "Hello world"
    assert fields["document_type"] == "invoice"


def test_parse_vision_analysis_fallback_plain_text():
    # Mistral OCR and other models that return plain text should be handled gracefully
    raw = "Just plain text from Mistral OCR"
    text, fields = _parse_vision_analysis(raw)
    assert text == raw
    assert fields == {}


def test_parse_vision_analysis_markdown_fenced():
    raw = "```json\n{\"text\": \"Doc text\", \"fields\": {\"language\": \"ru\"}}\n```"
    text, fields = _parse_vision_analysis(raw)
    assert text == "Doc text"
    assert fields["language"] == "ru"


def test_judge_prompt_corrected_is_conditional():
    # The prompt must instruct the model to skip corrected when not useful.
    for with_image in (True, False):
        prompt = _judge_system(with_image)
        assert "empty string" in prompt
