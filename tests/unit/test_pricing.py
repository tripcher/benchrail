"""Tests for pricing module."""

import pytest

from benchrail.pricing import (
    calc_claude_cost,
    calc_codex_cost,
    calc_codex_credits,
    get_claude_prices,
    get_codex_credits,
    get_codex_prices,
)


def test_claude_prices_lookup_exact() -> None:
    prices = get_claude_prices("claude-sonnet-4-6")
    assert prices is not None
    assert prices["input"] == 3.00
    assert prices["output"] == 15.00


def test_claude_prices_lookup_prefix() -> None:
    # Should match by prefix
    prices = get_claude_prices("claude-opus-4-8-20251234")
    assert prices is not None
    assert prices["input"] == 5.00


def test_claude_prices_unknown_model() -> None:
    prices = get_claude_prices("gpt-4o")
    assert prices is None


def test_calc_claude_cost_basic() -> None:
    cost = calc_claude_cost(
        "claude-sonnet-4-6",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )
    # 3.00 + 15.00 = 18.00
    assert cost == pytest.approx(18.00, rel=1e-5)


def test_calc_claude_cost_with_cache() -> None:
    cost = calc_claude_cost(
        "claude-sonnet-4-6",
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=1_000_000,
        cache_creation_tokens=1_000_000,
    )
    # 0.30 + 3.75 = 4.05
    assert cost == pytest.approx(4.05, rel=1e-5)


def test_calc_claude_cost_unknown_model() -> None:
    cost = calc_claude_cost("unknown-model", 1000, 1000)
    assert cost is None


def test_codex_prices_lookup() -> None:
    prices = get_codex_prices("o4-mini")
    assert prices is not None
    assert prices["input"] == 1.10
    assert prices["output"] == 4.40


def test_calc_codex_cost_basic() -> None:
    cost = calc_codex_cost(
        "o4-mini",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )
    # 1.10 + 4.40 = 5.50
    assert cost == pytest.approx(5.50, rel=1e-5)


def test_calc_codex_cost_with_cache() -> None:
    cost = calc_codex_cost(
        "o4-mini",
        input_tokens=1_000_000,
        output_tokens=0,
        cached_input_tokens=1_000_000,
    )
    # 1.10 + 0.275 = 1.375
    assert cost == pytest.approx(1.375, rel=1e-5)


def test_calc_codex_cost_unknown_model() -> None:
    cost = calc_codex_cost("gpt-99", 1000, 1000)
    assert cost is None


def test_codex_credits_lookup() -> None:
    prices = get_codex_credits("gpt-5.4")
    assert prices is not None
    assert prices["input"] == 62.50
    assert prices["output"] == 375


def test_calc_codex_credits_basic() -> None:
    credits = calc_codex_credits(
        "gpt-5.4",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )
    assert credits == pytest.approx(437.5, rel=1e-5)


def test_calc_codex_credits_with_cache() -> None:
    credits = calc_codex_credits(
        "gpt-5.4",
        input_tokens=1_000_000,
        output_tokens=0,
        cached_input_tokens=1_000_000,
    )
    assert credits == pytest.approx(68.75, rel=1e-5)


def test_calc_codex_credits_unknown_model() -> None:
    credits = calc_codex_credits("gpt-99", 1000, 1000)
    assert credits is None
