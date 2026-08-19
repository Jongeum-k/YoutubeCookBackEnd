# app/dtos/gemini.py

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class GeminiUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    thoughts_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0


@dataclass(frozen=True, slots=True)
class GeminiStreamChunk:
    text: str | None = None
    usage: GeminiUsage | None = None
    response_id: str | None = None
    model_version: str | None = None

@dataclass(frozen=True, slots=True)
class GeminiCost:
    total_usd: Decimal
    input_cost_usd: Decimal
    output_cost_usd: Decimal
    cached_input_cost_usd: Decimal
    pricing_version: str