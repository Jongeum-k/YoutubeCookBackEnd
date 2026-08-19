# app/routes/video.py

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.core.redis import redis_client
from app.dtos.gemini import GeminiUsage
from app.schemas.video import AnalyzeVideoRequest, RecipeAnalysis
from app.services.gemini import GeminiService
from app.services.quota import (
    InvalidTesterKeyError,
    QuotaExceededError,
    QuotaService,
)
from app.services.pricing import GeminiPricingService


router = APIRouter()

gemini_service = GeminiService()
quota_service = QuotaService(redis_client)
pricing_service = GeminiPricingService()


@router.websocket("/ws/analyze-video")
async def analyze_cooking_video(
    websocket: WebSocket,
) -> None:
    await websocket.accept()

    try:
        payload = await websocket.receive_json()

        request = AnalyzeVideoRequest.model_validate(payload)

        tester_count, global_count = await quota_service.consume(
            request.tester_key
        )

        await websocket.send_json(
            {
                "type": "quota",
                "used": tester_count,
                "global_used": global_count,
                "global_limit": 50,
            }
        )

        await websocket.send_json(
            {
                "type": "status",
                "status": "analyzing",
            }
        )

        chunks: list[str] = []
        usage: GeminiUsage | None = None
        response_id: str | None = None
        model_version: str | None = None

        cost = None

        async for chunk in gemini_service.analyze_cooking_video_stream(
            str(request.youtube_url)
        ):
            if chunk.text:
                chunks.append(chunk.text)

                await websocket.send_json(
                    {
                        "type": "delta",
                        "content": chunk.text,
                    }
                )

            if chunk.usage:
                usage = chunk.usage
                cost = pricing_service.calculate_cost(
                    model=gemini_service.model,
                    usage=usage,
                )

            if chunk.response_id:
                response_id = chunk.response_id

            if chunk.model_version:
                model_version = chunk.model_version

        raw_result = "".join(chunks)
        result = RecipeAnalysis.model_validate_json(raw_result)

        await websocket.send_json(
            {
                "type": "completed",
                "data": result.model_dump(),
                "model": gemini_service.model,
                "model_version": model_version,
                "response_id": response_id,
                "usage": (
                    {
                        "input_tokens": usage.input_tokens,
                        "output_tokens": usage.output_tokens,
                        "thoughts_tokens": usage.thoughts_tokens,
                        "total_tokens": usage.total_tokens,
                        "cached_tokens": usage.cached_tokens,
                    }
                    if usage
                    else None
                ),
                "cost": (
                    {
                        "total_usd": str(cost.total_usd),
                        "input_cost_usd": str(cost.input_cost_usd),
                        "output_cost_usd": str(cost.output_cost_usd),
                        "cached_input_cost_usd": str(
                            cost.cached_input_cost_usd
                        ),
                        "pricing_version": cost.pricing_version,
                    }
                    if cost
                    else None
                )
            }
        )

    except InvalidTesterKeyError:
        await websocket.send_json(
            {
                "type": "error",
                "code": "invalid_tester_key",
            }
        )

    except QuotaExceededError as exc:
        await websocket.send_json(
            {
                "type": "error",
                "code": "quota_exceeded",
                "message": str(exc),
            }
        )

    except WebSocketDisconnect:
        return

    except ValidationError as exc:
        await websocket.send_json(
            {
                "type": "error",
                "message": "Invalid request or Gemini response.",
                "detail": str(exc),
            }
        )

    except Exception as exc:
        await websocket.send_json(
            {
                "type": "error",
                "message": "Video analysis failed.",
                "detail": str(exc),
            }
        )

    finally:
        try:
            await websocket.close()
        except RuntimeError:
            pass