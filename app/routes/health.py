# app/api/routes/health.py

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db


router = APIRouter(
    prefix="/health",
    tags=["health"],
)


@router.get("/db")
async def check_database(
    db: AsyncSession = Depends(get_db),
):
    try:
        # 1. DB connection check
        await db.execute(text("SELECT 1"))

        # 2. Table existence check
        result = await db.execute(
            text("""
                SELECT
                    to_regclass('public.video_analyses') AS video_analyses,
                    to_regclass('public.gemini_requests') AS gemini_requests,
                    to_regclass('public.recipes') AS recipes,
                    to_regclass('public.recipe_ingredients') AS recipe_ingredients,
                    to_regclass('public.recipe_steps') AS recipe_steps
            """)
        )

        row = result.one()

        tables = {
            "video_analyses": row.video_analyses is not None,
            "gemini_requests": row.gemini_requests is not None,
            "recipes": row.recipes is not None,
            "recipe_ingredients": row.recipe_ingredients is not None,
            "recipe_steps": row.recipe_steps is not None,
        }

        return {
            "status": "ok" if all(tables.values()) else "degraded",
            "database": "connected",
            "tables": tables,
        }

    except Exception as exc:
        return {
            "status": "error",
            "database": "disconnected",
            "error": str(exc),
        }