"""
Per-model token pricing (USD per token) for cost estimation.
Sources: official provider pricing pages (June 2025) and OpenRouter.

For unknown models estimate_cost() returns 0.0 — better than a wrong number.
"""

# (price_in_per_token, price_out_per_token) in USD
_PRICES: dict[str, tuple[float, float]] = {
    # ── Anthropic ────────────────────────────────────────────────────────────
    "claude-haiku-4-5-20251001":    (0.80e-6,  4.00e-6),
    "claude-3-5-haiku-20241022":    (0.80e-6,  4.00e-6),
    "claude-3-haiku-20240307":      (0.25e-6,  1.25e-6),
    "claude-sonnet-4-6":            (3.00e-6, 15.00e-6),
    "claude-3-5-sonnet-20241022":   (3.00e-6, 15.00e-6),
    "claude-3-7-sonnet-20250219":   (3.00e-6, 15.00e-6),
    "claude-opus-4-8":             (15.00e-6, 75.00e-6),
    "claude-3-opus-20240229":      (15.00e-6, 75.00e-6),
    # ── OpenAI ──────────────────────────────────────────────────────────────
    "gpt-4o":                       (2.50e-6, 10.00e-6),
    "gpt-4o-mini":                  (0.15e-6,  0.60e-6),
    "gpt-4-turbo":                 (10.00e-6, 30.00e-6),
    "gpt-3.5-turbo":                (0.50e-6,  1.50e-6),
    # ── Gemini ──────────────────────────────────────────────────────────────
    "gemini-2.5-flash":             (0.15e-6,  0.60e-6),
    "gemini-2.5-flash-preview-05-20": (0.15e-6, 0.60e-6),
    "gemini-2.5-flash-lite":        (0.10e-6,  0.40e-6),
    "gemini-2.5-pro":               (1.25e-6,  5.00e-6),
    "gemini-2.5-pro-preview-06-05": (1.25e-6,  5.00e-6),
    "gemini-2.0-flash":             (0.10e-6,  0.40e-6),
    "gemini-2.0-flash-lite":        (0.075e-6, 0.30e-6),
    "gemini-2.0-flash-exp":         (0.10e-6,  0.40e-6),
    "gemini-3.0-flash":             (0.15e-6,  0.60e-6),
    "gemini-3.1-flash-lite-preview": (0.10e-6, 0.40e-6),
    "gemini-3.1-flash-preview":     (0.15e-6,  0.60e-6),
    "gemini-1.5-flash":             (0.075e-6, 0.30e-6),
    "gemini-1.5-flash-002":         (0.075e-6, 0.30e-6),
    "gemini-1.5-pro":               (1.25e-6,  5.00e-6),
    "gemini-1.5-pro-002":           (1.25e-6,  5.00e-6),
    # ── DeepSeek ─────────────────────────────────────────────────────────────
    "deepseek-chat":                (0.27e-6,  1.10e-6),
    "deepseek-reasoner":            (0.55e-6,  2.19e-6),
    # ── Mistral text models (not OCR endpoint) ───────────────────────────────
    "mistral-small-latest":         (0.10e-6,  0.30e-6),
    "mistral-medium-latest":        (0.30e-6,  0.90e-6),
    "mistral-large-latest":         (2.00e-6,  6.00e-6),
    "pixtral-large-latest":         (2.00e-6,  6.00e-6),
    "pixtral-12b-2409":             (0.15e-6,  0.15e-6),
    # ── OpenRouter (provider/model format) ──────────────────────────────────
    "openai/gpt-4o":                (2.50e-6, 10.00e-6),
    "openai/gpt-4o-mini":           (0.15e-6,  0.60e-6),
    "anthropic/claude-3.5-sonnet":  (3.00e-6, 15.00e-6),
    "anthropic/claude-3.5-haiku":   (0.80e-6,  4.00e-6),
    "anthropic/claude-3-haiku":     (0.25e-6,  1.25e-6),
    "google/gemini-2.5-flash":      (0.15e-6,  0.60e-6),
    "google/gemini-flash-1.5":      (0.075e-6, 0.30e-6),
    "google/gemini-pro-1.5":        (1.25e-6,  5.00e-6),
    "deepseek/deepseek-chat":       (0.27e-6,  1.10e-6),
    "deepseek/deepseek-r1":         (0.55e-6,  2.19e-6),
    "mistralai/mistral-large":      (2.00e-6,  6.00e-6),
    "mistralai/pixtral-large":      (2.00e-6,  6.00e-6),
    "meta-llama/llama-3.1-70b-instruct":   (0.40e-6, 0.40e-6),
    "meta-llama/llama-3.1-405b-instruct":  (2.70e-6, 2.70e-6),
    "meta-llama/llama-3.3-70b-instruct":   (0.40e-6, 0.40e-6),
}


def estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """Return estimated cost in USD. Returns 0.0 for unknown models."""
    price_in, price_out = _PRICES.get(model, (0.0, 0.0))
    return tokens_in * price_in + tokens_out * price_out
