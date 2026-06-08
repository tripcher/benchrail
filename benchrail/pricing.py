# Claude (Anthropic) prices per million tokens
_CLAUDE_PRICES: list[tuple[str, dict[str, float]]] = [
    ("claude-opus-4-8", {"input": 5.00, "cache_write": 6.25, "cache_read": 0.50, "output": 25.00}),
    ("claude-opus-4-7", {"input": 5.00, "cache_write": 6.25, "cache_read": 0.50, "output": 25.00}),
    ("claude-opus-4-6", {"input": 5.00, "cache_write": 6.25, "cache_read": 0.50, "output": 25.00}),
    ("claude-opus-4-5", {"input": 5.00, "cache_write": 6.25, "cache_read": 0.50, "output": 25.00}),
    (
        "claude-opus-4-1",
        {"input": 15.00, "cache_write": 18.75, "cache_read": 1.50, "output": 75.00},
    ),
    ("claude-opus-4", {"input": 15.00, "cache_write": 18.75, "cache_read": 1.50, "output": 75.00}),
    (
        "claude-sonnet-4-6",
        {"input": 3.00, "cache_write": 3.75, "cache_read": 0.30, "output": 15.00},
    ),
    (
        "claude-sonnet-4-5",
        {"input": 3.00, "cache_write": 3.75, "cache_read": 0.30, "output": 15.00},
    ),
    ("claude-sonnet-4", {"input": 3.00, "cache_write": 3.75, "cache_read": 0.30, "output": 15.00}),
    ("claude-haiku-4-5", {"input": 1.00, "cache_write": 1.25, "cache_read": 0.10, "output": 5.00}),
    ("claude-haiku-3-5", {"input": 0.80, "cache_write": 1.00, "cache_read": 0.08, "output": 4.00}),
]

# Codex / OpenAI prices per million tokens
_CODEX_PRICES: list[tuple[str, dict[str, float]]] = [
    ("gpt-5.5", {"input": 5.00, "cached_input": 0.50, "output": 30.00}),
    ("gpt-5.4-mini", {"input": 0.75, "cached_input": 0.075, "output": 4.50}),
    ("gpt-5.4", {"input": 2.50, "cached_input": 0.25, "output": 15.00}),
    ("o4-mini", {"input": 1.10, "cached_input": 0.275, "output": 4.40}),
    ("o3", {"input": 2.00, "cached_input": 0.50, "output": 8.00}),
]

# Codex subscription credits per million tokens
_CODEX_CREDITS: list[tuple[str, dict[str, float]]] = [
    ("gpt-5.5", {"input": 125, "cached_input": 12.50, "output": 750}),
    ("gpt-5.4-mini", {"input": 18.75, "cached_input": 1.875, "output": 113}),
    ("gpt-5.4", {"input": 62.50, "cached_input": 6.25, "output": 375}),
    ("gpt-5.3-codex", {"input": 43.75, "cached_input": 4.375, "output": 350}),
    ("gpt-5.2", {"input": 43.75, "cached_input": 4.375, "output": 350}),
]


def _find_price(
    table: list[tuple[str, dict[str, float]]], model_id: str
) -> dict[str, float] | None:
    for prefix, prices in table:
        if model_id.startswith(prefix):
            return prices
    return None


def get_claude_prices(model_id: str) -> dict[str, float] | None:
    return _find_price(_CLAUDE_PRICES, model_id)


def get_codex_prices(model_id: str) -> dict[str, float] | None:
    return _find_price(_CODEX_PRICES, model_id)


def get_codex_credits(model_id: str) -> dict[str, float] | None:
    return _find_price(_CODEX_CREDITS, model_id)


def calc_claude_cost(
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> float | None:
    prices = get_claude_prices(model_id)
    if prices is None:
        return None
    mtok = 1_000_000
    cost = (
        input_tokens / mtok * prices["input"]
        + output_tokens / mtok * prices["output"]
        + cache_read_tokens / mtok * prices["cache_read"]
        + cache_creation_tokens / mtok * prices["cache_write"]
    )
    return float(round(cost, 6))


def calc_codex_cost(
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
) -> float | None:
    prices = get_codex_prices(model_id)
    if prices is None:
        return None
    mtok = 1_000_000
    cost = (
        input_tokens / mtok * prices["input"]
        + cached_input_tokens / mtok * prices["cached_input"]
        + output_tokens / mtok * prices["output"]
    )
    return float(round(cost, 6))


def calc_codex_credits(
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
) -> float | None:
    prices = get_codex_credits(model_id)
    if prices is None:
        return None
    mtok = 1_000_000
    credits = (
        input_tokens / mtok * prices["input"]
        + cached_input_tokens / mtok * prices["cached_input"]
        + output_tokens / mtok * prices["output"]
    )
    return float(round(credits, 4))
