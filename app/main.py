from fastapi import FastAPI

from app.api.routes import test_router
from app.routes.video import router

app = FastAPI(
    title="YouTube Cook Backend",
    description="Backend API for extracting recipes from cooking videos.",
    version="0.1.0",
)

app.include_router(
    test_router,
    prefix="/api/v0",
)

app.include_router(
    router,
    prefix="/api/v1",
)


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "service": "youtube-cook-backend",
        "status": "running",
    }