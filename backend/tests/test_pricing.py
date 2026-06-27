"""Pins token cost estimation — see docs/code-map.md (services/pricing.py).

`estimate_cost` is a pure per-token lookup used by every AI provider call to
fill `api_cost_*`. Rules worth pinning: exact per-token math, 0.0 for unknown
models (better than a wrong number), and linear scaling with token counts.
"""
from app.services.pricing import estimate_cost


def test_estimate_cost_known_model_uses_per_token_table():
    # Rule: cost = tokens_in*price_in + tokens_out*price_out.
    # gpt-4o-mini = (0.15e-6, 0.60e-6) → 1M in + 1M out = 0.15 + 0.60 = 0.75.
    assert round(estimate_cost("gpt-4o-mini", 1_000_000, 1_000_000), 6) == 0.75


def test_estimate_cost_unknown_model_returns_zero():
    # Rule: unknown model → 0.0 (documented: "better than a wrong number").
    assert estimate_cost("some-model-we-never-priced", 5000, 5000) == 0.0


def test_estimate_cost_scales_linearly_and_handles_zero():
    # Rule: zero tokens → zero cost; output-only billing is counted.
    assert estimate_cost("claude-haiku-4-5-20251001", 0, 0) == 0.0
    only_out = estimate_cost("claude-haiku-4-5-20251001", 0, 1_000_000)
    assert round(only_out, 6) == 4.0  # 4.00e-6 * 1M
