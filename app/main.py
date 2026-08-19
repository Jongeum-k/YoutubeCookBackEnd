from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import test_router
from app.routes.video import router
from app.routes.health import router as health_router
from app.routes.dashboard import router as dashboard_router

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

app.include_router(
    health_router,
    prefix="/api/v1",
)

app.include_router(
    dashboard_router,
    prefix="/api/v1",
)



app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5500",
        "http://127.0.0.1:5500",
    ],
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["X-Tester-Key"],
)

@app.get("/")
async def root() -> dict[str, str]:
    return {
        "service": "youtube-cook-backend",
        "status": "running",
    }