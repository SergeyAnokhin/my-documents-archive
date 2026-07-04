"""Model-level capability resolution with per-provider manual overrides."""

from __future__ import annotations

from typing import Any

from .provider_models import KNOWN_MODELS, _gemini_infer_pricing


CAPABILITY_KEYS = ("text", "vision", "ocr", "analysis", "batch")


def inferred_capabilities(provider_type: str, model: str | None) -> dict[str, bool]:
    model_id = (model or "").lower()
    known = KNOWN_MODELS.get(model or "", {})
    vision = bool(known.get("vision", False))
    if provider_type == "gemini" and model_id:
        vision = bool(_gemini_infer_pricing(model_id).get("vision", True))

    is_mistral_ocr = provider_type == "mistral" and (
        model_id.startswith("mistral-ocr") or not model_id
    )
    return {
        "text": not is_mistral_ocr,
        "vision": vision or is_mistral_ocr,
        "ocr": vision or is_mistral_ocr,
        "analysis": not is_mistral_ocr,
        "batch": provider_type in {"gemini", "mistral"},
    }


def provider_capabilities(provider: Any) -> dict[str, bool]:
    """Return inferred capabilities merged with explicit extra_params overrides."""
    result = inferred_capabilities(provider.provider_type, getattr(provider, "model", None))
    overrides = (getattr(provider, "extra_params", None) or {}).get("capabilities", {})
    if isinstance(overrides, dict):
        for key in CAPABILITY_KEYS:
            if key in overrides and isinstance(overrides[key], bool):
                result[key] = overrides[key]
    return result


def supports(provider: Any, capability: str) -> bool:
    return provider_capabilities(provider).get(capability, False)
