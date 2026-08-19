# app/services/pricing.py


from decimal import Decimal, ROUND_HALF_UP

from app.dtos.gemini import GeminiUsage, GeminiCost
from app.pricing.gemini import (
    GEMINI_PRICING_SNAPSHOTS,
    GeminiPricingSnapshot,
)


class GeminiPricingService:
    TOKENS_PER_MILLION = Decimal("1000000")

    def get_snapshot(
        self,
        model: str,
    ) -> GeminiPricingSnapshot:
        try:
            return GEMINI_PRICING_SNAPSHOTS[model]
        except KeyError as exc:
            raise ValueError(
                f"No pricing snapshot configured for model: {model}"
            ) from exc

    def calculate_cost(
        self,
        *,
        model: str,
        usage: GeminiUsage,
    ) -> GeminiCost:
        snapshot = self.get_snapshot(model)

        cached_tokens = usage.cached_tokens

        regular_input_tokens = max(
            usage.input_tokens - cached_tokens,
            0,
        )

        input_cost = (
            Decimal(regular_input_tokens)
            / self.TOKENS_PER_MILLION
            * snapshot.input_per_million
        )

        cached_input_cost = (
            Decimal(cached_tokens)
            / self.TOKENS_PER_MILLION
            * snapshot.cached_input_per_million
        )

        billable_output_tokens = (
            usage.output_tokens + usage.thoughts_tokens
        )
        # The cost includes thinking tokens, too.

        output_cost = (
            Decimal(billable_output_tokens)
            / self.TOKENS_PER_MILLION
            * snapshot.output_per_million
        )

        total_cost = (
            input_cost
            + cached_input_cost
            + output_cost
        )

        quantizer = Decimal("0.00000001")

        return GeminiCost(
            total_usd=total_cost.quantize(
                quantizer,
                rounding=ROUND_HALF_UP,
            ),
            input_cost_usd=input_cost.quantize(
                quantizer,
                rounding=ROUND_HALF_UP,
            ),
            output_cost_usd=output_cost.quantize(
                quantizer,
                rounding=ROUND_HALF_UP,
            ),
            cached_input_cost_usd=cached_input_cost.quantize(
                quantizer,
                rounding=ROUND_HALF_UP,
            ),
            pricing_version=snapshot.version,
        )