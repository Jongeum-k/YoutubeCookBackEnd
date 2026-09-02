# app/routes/video.py

from datetime import datetime, timezone
from time import perf_counter
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.redis import redis_client
from app.db.session import AsyncSessionLocal
from app.dtos.gemini import GeminiUsage
from app.dtos.quota import QuotaReservation
from app.enums import (
    GeminiRequestStatus,
    GeminiRequestType,
    VideoAnalysisStatus,
)
from app.models import (
    GeminiRequest,
    Recipe,
    RecipeIngredient,
    RecipeStep,
    VideoAnalysis,
)
from app.schemas.video import AnalyzeVideoRequest, RecipeAnalysis
from app.services.gemini import GeminiService
from app.services.pricing import GeminiPricingService
from app.services.quota import (
    InvalidTesterKeyError,
    QuotaExceededError,
    QuotaService,
)
from app.utils.youtube import extract_youtube_video_id


router = APIRouter()

gemini_service = GeminiService()
quota_service = QuotaService(redis_client)
pricing_service = GeminiPricingService()


class InvalidYoutubeUrlError(Exception):
    pass


def recipe_to_dict(recipe: Recipe) -> dict:
    """Reshape a stored Recipe (+ children) into the same dict shape
    RecipeAnalysis.model_dump() produces, so cached and freshly
    analyzed responses look identical to the client."""

    return {
        "basic_info": {
            "title": recipe.title,
            "description": recipe.description,
            "servings": recipe.servings,
            "cuisine": recipe.cuisine,
        },
        "ingredients": [
            {
                "name": ingredient.name,
                "amount": ingredient.amount,
                "unit": ingredient.unit,
                "note": ingredient.note,
            }
            for ingredient in recipe.ingredients
        ],
        "steps": [
            {
                "order": step.step_order,
                "instruction": step.instruction,
                "start_seconds": step.start_seconds,
                "end_seconds": step.end_seconds,
                "temperature": step.temperature,
                "duration": step.duration,
            }
            for step in recipe.steps
        ],
        "tips": list(recipe.tips),
    }


def recipe_to_analysis(recipe: Recipe) -> RecipeAnalysis:
    return RecipeAnalysis.model_validate(recipe_to_dict(recipe))


async def load_recipes(youtube_video_id: str) -> list[Recipe]:
    """Recipes are looked up directly by video id -- independent of
    video_analyses, which stays a plain request log (many rows per
    video, one per request, regardless of outcome)."""

    async with AsyncSessionLocal() as db:
        recipes = await db.scalars(
            select(Recipe)
            .where(Recipe.youtube_video_id == youtube_video_id)
            .options(
                selectinload(Recipe.ingredients),
                selectinload(Recipe.steps),
            )
        )

        return list(recipes)


async def persist_recipe(
    db: AsyncSession,
    *,
    youtube_video_id: str,
    language: str,
    result: RecipeAnalysis,
) -> None:
    recipe = Recipe(
        youtube_video_id=youtube_video_id,
        language=language,
        title=result.basic_info.title,
        description=result.basic_info.description,
        servings=result.basic_info.servings,
        cuisine=result.basic_info.cuisine,
        tips=result.tips,
    )

    db.add(recipe)
    await db.flush()

    db.add_all(
        RecipeIngredient(
            recipe_id=recipe.id,
            sort_order=index,
            name=ingredient.name,
            amount=ingredient.amount,
            unit=ingredient.unit,
            note=ingredient.note,
        )
        for index, ingredient in enumerate(result.ingredients)
    )

    db.add_all(
        RecipeStep(
            recipe_id=recipe.id,
            step_order=step.order,
            instruction=step.instruction,
            start_seconds=step.start_seconds,
            end_seconds=step.end_seconds,
            temperature=step.temperature,
            duration=step.duration,
        )
        for step in result.steps
    )


async def create_analysis_records(
    *,
    youtube_video_id: str,
    youtube_url: str,
    model_name: str,
    request_type: str,
    language: str,
) -> tuple[UUID, UUID]:
    """Every request gets its own video_analyses row -- one row per
    request, success or failure, exactly as before this feature."""

    async with AsyncSessionLocal() as db:
        analysis = VideoAnalysis(
            youtube_video_id=youtube_video_id,
            youtube_url=youtube_url,
            status=VideoAnalysisStatus.PROCESSING.value,
        )

        db.add(analysis)
        await db.flush()

        gemini_request = GeminiRequest(
            analysis_id=analysis.id,
            attempt_number=1,
            model_name=model_name,
            request_type=request_type,
            language=language,
            status=GeminiRequestStatus.PROCESSING.value,
        )

        db.add(gemini_request)

        await db.commit()

        return analysis.id, gemini_request.id


async def complete_analysis_records(
    *,
    analysis_id: UUID,
    gemini_request_id: UUID,
    youtube_video_id: str,
    language: str,
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
        analysis.title = result.basic_info.title

        await persist_recipe(
            db,
            youtube_video_id=youtube_video_id,
            language=language,
            result=result,
        )

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

        await websocket.send_json(
            {
                "type": "quota",
                "used": reservation.tester_count,
                "global_used": reservation.global_count,
                "global_limit": 50,
            }
        )

        youtube_video_id = extract_youtube_video_id(
            str(request.youtube_url)
        )

        if youtube_video_id is None:
            raise InvalidYoutubeUrlError(str(request.youtube_url))

        existing_recipes = await load_recipes(youtube_video_id)

        target_recipe = next(
            (
                recipe
                for recipe in existing_recipes
                if recipe.language == request.language
            ),
            None,
        )

        # --- cache hit: this video already has this language ---
        if target_recipe is not None:
            await quota_service.commit(reservation)
            reservation = None

            await websocket.send_json(
                {
                    "type": "completed",
                    "cached": True,
                    "data": recipe_to_dict(target_recipe),
                    "model": None,
                    "model_version": None,
                    "response_id": None,
                    "usage": None,
                    "cost": None,
                }
            )
            return

        source_recipe = next(
            (
                recipe
                for recipe in existing_recipes
                if recipe.language != request.language
            ),
            None,
        )

        is_translation = source_recipe is not None
        request_type = (
            GeminiRequestType.TRANSLATION.value
            if is_translation
            else GeminiRequestType.ANALYSIS.value
        )
        model_name = (
            gemini_service.translation_model
            if is_translation
            else gemini_service.model
        )

        await websocket.send_json(
            {
                "type": "status",
                "status": "analyzing",
            }
        )

        analysis_id, gemini_request_id = await create_analysis_records(
            youtube_video_id=youtube_video_id,
            youtube_url=str(request.youtube_url),
            model_name=model_name,
            request_type=request_type,
            language=request.language,
        )

        chunks: list[str] = []

        usage: GeminiUsage | None = None
        response_id: str | None = None
        model_version: str | None = None

        cost = None

        gemini_started_at = perf_counter()

        if is_translation:
            stream = gemini_service.translate_recipe_stream(
                recipe_to_analysis(source_recipe),
                target_language=request.language,
            )
        else:
            stream = gemini_service.analyze_cooking_video_stream(
                str(request.youtube_url)
            )

        async for chunk in stream:
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

                try:
                    cost = pricing_service.calculate_cost(
                        model=model_name,
                        usage=usage,
                    )
                except ValueError:
                    # No pricing snapshot configured for this model yet
                    # (e.g. a freshly-set translation model). Keep the
                    # recipe itself working; cost just won't be tracked
                    # until a snapshot is added.
                    cost = None

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
            youtube_video_id=youtube_video_id,
            language=request.language,
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
                "cached": False,
                "data": result.model_dump(),
                "model": model_name,
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

    except InvalidYoutubeUrlError as exc:
        if reservation:
            await quota_service.rollback(reservation)

        await websocket.send_json(
            {
                "type": "error",
                "code": "invalid_youtube_url",
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
