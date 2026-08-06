from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from app.schemas import AnalyzeTextRequest, AnalyzeTextResponse
from app.services.gemini import GeminiService

router = APIRouter()

gemini_service = GeminiService()


@router.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/analyze", response_model=AnalyzeTextResponse)
async def analyze_cooking_text(
    request: AnalyzeTextRequest,
) -> AnalyzeTextResponse:
    try:
        result = await run_in_threadpool(
            gemini_service.analyze_cooking_text,
            request.text,
        )

        return AnalyzeTextResponse(
            result=result,
            model=gemini_service.model,
        )

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Gemini API request failed: {exc}",
        ) from exc