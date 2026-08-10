# app/routes/video.py

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.schemas.video import AnalyzeVideoRequest, RecipeAnalysis
from app.services.gemini import GeminiService


router = APIRouter()

gemini_service = GeminiService()


@router.websocket("/ws/analyze-video")
async def analyze_cooking_video(
    websocket: WebSocket,
) -> None:
    await websocket.accept()

    try:
        payload = await websocket.receive_json()

        request = AnalyzeVideoRequest.model_validate(payload)

        await websocket.send_json(
            {
                "type": "status",
                "status": "analyzing",
            }
        )

        chunks: list[str] = []

        async for chunk in gemini_service.analyze_cooking_video_stream(
            str(request.youtube_url)
        ):
            chunks.append(chunk)

            await websocket.send_json(
                {
                    "type": "delta",
                    "content": chunk,
                }
            )

        raw_result = "".join(chunks)

        result = RecipeAnalysis.model_validate_json(raw_result)

        await websocket.send_json(
            {
                "type": "completed",
                "data": result.model_dump(),
                "model": gemini_service.model,
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