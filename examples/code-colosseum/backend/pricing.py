"""Simple token-cost model for Code Colosseum.

Prices are configurable via environment variables and default to placeholder
OpenAI-like rates.  The same model is used for every agent because all current
backends route through the Kimi Code API; the differences in cost come from
different prompting strategies and reflection loops.
"""

import os


DEFAULT_PROMPT_PRICE_PER_1K = float(os.environ.get("PROMPT_PRICE_PER_1K", "0.0015"))
DEFAULT_COMPLETION_PRICE_PER_1K = float(
    os.environ.get("COMPLETION_PRICE_PER_1K", "0.0060")
)


def estimate_cost(usage: dict) -> float:
    """Estimate dollar cost from prompt/completion token counts."""
    if not usage:
        return 0.0
    prompt = int(usage.get("prompt_tokens", 0))
    completion = int(usage.get("completion_tokens", 0))
    return (
        prompt * DEFAULT_PROMPT_PRICE_PER_1K / 1000
        + completion * DEFAULT_COMPLETION_PRICE_PER_1K / 1000
    )
