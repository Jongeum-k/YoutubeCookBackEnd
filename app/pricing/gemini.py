# app/pricing/gemini.py
## snapshot for price calculation

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class GeminiPricingSnapshot:
    version: str
    model: str
    input_per_million: Decimal
    output_per_million: Decimal
    cached_input_per_million: Decimal

# Valid till 2026-12-31
GEMINI_36_FLASH_2026 = GeminiPricingSnapshot(
    version="gemini-3.6-flash-2026-07-21",
    model="gemini-3.6-flash",
    input_per_million=Decimal("0.75"),
    output_per_million=Decimal("3.75"),
    cached_input_per_million=Decimal("0.075"),
)


GEMINI_PRICING_SNAPSHOTS = {
    "gemini-3.6-flash": GEMINI_36_FLASH_2026,
}