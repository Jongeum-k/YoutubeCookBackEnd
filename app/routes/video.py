# app/routes/video.py

from datetime import datetime, timezone
from time import perf_counter
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from sqlalchemy import select

from app.core.redis import redis_client
from app.db.session import AsyncSessionLocal
from app.dtos.gemini import GeminiUsage
from app.dtos.quota import QuotaReservation
from app.enums import GeminiRequestStatus, VideoAnalysisStatus
from app.models import GeminiRequest, VideoAnalysis
from app.schemas.video import AnalyzeVideoRequest, RecipeAnalysis
from app.services.gemini import GeminiService
from app.services.pricing import GeminiPricingService
from app.services.quota import (
    InvalidTesterKeyError,
    QuotaExceededError,
    QuotaService,
)


router = APIRouter()

gemini_service = GeminiService()
quota_service = QuotaService(redis_client)
pricing_service = GeminiPricingService()


async def create_analysis_records(
    *,
    youtube_url: str,
    model_name: str,
) -> tuple[UUID, UUID]:
    async with AsyncSessionLocal() as db:
        analysis = VideoAnalysis(
            youtube_url=youtube_url,
            status=VideoAnalysisStatus.PROCESSING.value,
        )

        db.add(analysis)
        await db.flush()

        gemini_request = GeminiRequest(
            analysis_id=analysis.id,
            attempt_number=1,
            model_name=model_name,
            status=GeminiRequestStatus.PROCESSING.value,
        )

        db.add(gemini_request)

        await db.commit()

        return analysis.id, gemini_request.id


async def complete_analysis_records(
    *,
    analysis_id: UUID,
    gemini_request_id: UUID,
    result: RecipeAnalysis,
    usage: GeminiUsage | None,
    cost,
    analysis_duration_ms: int,
    gemini_duration_ms: int,
) -> None:
    async with AsyncSessionLocal() as db:
        analysis = await db.get(
            VideoAnalysis,
            analysis_id,
        )

        gemini_request = await db.get(
            GeminiRequest,
            gemini_request_id,
        )

        if analysis is None or gemini_request is None:
            raise RuntimeError(
                "Analysis database records were not found."
            )

        now = datetime.now(timezone.utc)

        analysis.status = VideoAnalysisStatus.COMPLETED.value
        analysis.processing_duration_ms = analysis_duration_ms
        analysis.processed_at = now

        # RecipeAnalysis의 실제 schema가 basic_info.title 구조라면 이 형태.
        analysis.title = result.basic_info.title

        gemini_request.status = GeminiRequestStatus.COMPLETED.value
        gemini_request.duration_ms = gemini_duration_ms
        gemini_request.completed_at = now

        if usage:
            gemini_request.input_tokens = usage.input_tokens
            gemini_request.output_tokens = usage.output_tokens
            gemini_request.thoughts_tokens = usage.thoughts_tokens
            gemini_request.total_tokens = usage.total_tokens
            gemini_request.cached_tokens = usage.cached_tokens

        if cost:
            gemini_request.cost_usd = cost.total_usd

            # pricing_version 컬럼도 실제 모델에 추가했다면 활성화.
            # gemini_request.pricing_version = cost.pricing_version

        await db.commit()


async def fail_analysis_records(
    *,
    analysis_id: UUID | None,
    gemini_request_id: UUID | None,
    error: Exception,
    analysis_duration_ms: int,
    gemini_duration_ms: int | None,
) -> None:
    if analysis_id is None:
        return

    async with AsyncSessionLocal() as db:
        analysis = await db.get(
            VideoAnalysis,
            analysis_id,
        )

        gemini_request = (
            await db.get(
                GeminiRequest,
                gemini_request_id,
            )
            if gemini_request_id
            else None
        )

        now = datetime.now(timezone.utc)

        if analysis:
            analysis.status = VideoAnalysisStatus.FAILED.value
            analysis.processing_duration_ms = analysis_duration_ms
            analysis.processed_at = now

        if gemini_request:
            gemini_request.status = GeminiRequestStatus.FAILED.value
            gemini_request.completed_at = now

            if gemini_duration_ms is not None:
                gemini_request.duration_ms = gemini_duration_ms

            gemini_request.error_type = type(error).__name__[:50]
            gemini_request.error_message = str(error)

            status_code = getattr(
                error,
                "status_code",
                None,
            )

            if status_code is None:
                status_code = getattr(
                    error,
                    "code",
                    None,
                )

            if isinstance(status_code, int):
                if 100 <= status_code <= 599:
                    gemini_request.http_status = status_code

        await db.commit()


@router.websocket("/ws/analyze-video")
async def analyze_cooking_video(
    websocket: WebSocket,
) -> None:
    await websocket.accept()

    reservation: QuotaReservation | None = None

    analysis_id: UUID | None = None
    gemini_request_id: UUID | None = None

    analysis_started_at = perf_counter()
    gemini_started_at: float | None = None

    try:
        payload = await websocket.receive_json()

        request = AnalyzeVideoRequest.model_validate(payload)

        reservation = await quota_service.reserve(
            request.tester_key
        )

        analysis_id, gemini_request_id = (
            await create_analysis_records(
                youtube_url=str(request.youtube_url),
                model_name=gemini_service.model,
            )
        )

        await websocket.send_json(
            {
                "type": "quota",
                "used": reservation.tester_count,
                "global_used": reservation.global_count,
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

        gemini_started_at = perf_counter()

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

        gemini_duration_ms = int(
            (perf_counter() - gemini_started_at) * 1000
        )

        raw_result = "".join(chunks)

        result = RecipeAnalysis.model_validate_json(
            raw_result
        )

        analysis_duration_ms = int(
            (perf_counter() - analysis_started_at) * 1000
        )

        await complete_analysis_records(
            analysis_id=analysis_id,
            gemini_request_id=gemini_request_id,
            result=result,
            usage=usage,
            cost=cost,
            analysis_duration_ms=analysis_duration_ms,
            gemini_duration_ms=gemini_duration_ms,
        )

        await quota_service.commit(reservation)
        reservation = None

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
                        "input_cost_usd": str(
                            cost.input_cost_usd
                        ),
                        "output_cost_usd": str(
                            cost.output_cost_usd
                        ),
                        "cached_input_cost_usd": str(
                            cost.cached_input_cost_usd
                        ),
                        "pricing_version": cost.pricing_version,
                    }
                    if cost
                    else None
                ),
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

    except WebSocketDisconnect as exc:
        if analysis_id:
            await fail_analysis_records(
                analysis_id=analysis_id,
                gemini_request_id=gemini_request_id,
                error=exc,
                analysis_duration_ms=int(
                    (perf_counter() - analysis_started_at) * 1000
                ),
                gemini_duration_ms=(
                    int(
                        (
                            perf_counter()
                            - gemini_started_at
                        )
                        * 1000
                    )
                    if gemini_started_at
                    else None
                ),
            )

        if reservation:
            await quota_service.rollback(reservation)

        return

    except ValidationError as exc:
        if analysis_id:
            await fail_analysis_records(
                analysis_id=analysis_id,
                gemini_request_id=gemini_request_id,
                error=exc,
                analysis_duration_ms=int(
                    (perf_counter() - analysis_started_at) * 1000
                ),
                gemini_duration_ms=(
                    int(
                        (
                            perf_counter()
                            - gemini_started_at
                        )
                        * 1000
                    )
                    if gemini_started_at
                    else None
                ),
            )

        if reservation:
            await quota_service.rollback(reservation)

        await websocket.send_json(
            {
                "type": "error",
                "message": "Invalid request or Gemini response.",
                "detail": str(exc),
            }
        )

    except Exception as exc:
        if analysis_id:
            try:
                await fail_analysis_records(
                    analysis_id=analysis_id,
                    gemini_request_id=gemini_request_id,
                    error=exc,
                    analysis_duration_ms=int(
                        (
                            perf_counter()
                            - analysis_started_at
                        )
                        * 1000
                    ),
                    gemini_duration_ms=(
                        int(
                            (
                                perf_counter()
                                - gemini_started_at
                            )
                            * 1000
                        )
                        if gemini_started_at
                        else None
                    ),
                )
            except Exception:
                # 원래 발생한 예외를 DB logging 실패로 덮어쓰지 않는다.
                pass

        if reservation:
            try:
                await quota_service.rollback(reservation)
            except Exception:
                pass

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