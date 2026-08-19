# app/services/dashboard.py

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GeminiRequest, VideoAnalysis
from app.schemas.dashboard import (
    DashboardOverview,
    DashboardResponse,
    DailyDetail,
    DailyTokenUsage,
    ProcessedVideoItem,
    TodayMetrics,
)


def _successful_gemini_usage_subquery():
    """
    Aggregate successful Gemini requests per video analysis.

    Failed requests are intentionally excluded from dashboard metrics.
    """
    return (
        select(
            GeminiRequest.analysis_id.label("analysis_id"),
            func.sum(GeminiRequest.total_tokens).label("total_tokens"),
            func.sum(GeminiRequest.cost_usd).label("cost_usd"),
        )
        .where(GeminiRequest.status == "completed")
        .group_by(GeminiRequest.analysis_id)
        .subquery()
    )


async def _get_overview(
    db: AsyncSession,
) -> DashboardOverview:
    usage = _successful_gemini_usage_subquery()

    stmt = (
        select(
            func.count(VideoAnalysis.id).label("total_videos"),
            func.coalesce(
                func.sum(VideoAnalysis.video_duration_seconds),
                0,
            ).label("total_playtime_seconds"),
            func.coalesce(
                func.sum(usage.c.total_tokens),
                0,
            ).label("total_tokens"),
            func.coalesce(
                func.sum(usage.c.cost_usd),
                Decimal("0"),
            ).label("total_cost_usd"),
        )
        .outerjoin(
            usage,
            usage.c.analysis_id == VideoAnalysis.id,
        )
        .where(VideoAnalysis.status == "completed")
    )

    result = await db.execute(stmt)
    row = result.one()

    return DashboardOverview(
        total_videos=row.total_videos,
        total_playtime_seconds=row.total_playtime_seconds,
        total_tokens=row.total_tokens,
        total_cost_usd=row.total_cost_usd,
    )


async def _get_daily_details(
    db: AsyncSession,
    start_date: date,
    end_date: date,
) -> list[DailyDetail]:
    usage = _successful_gemini_usage_subquery()

    processed_date = func.date(VideoAnalysis.processed_at)

    stmt = (
        select(
            processed_date.label("date"),
            func.count(VideoAnalysis.id).label("total_videos"),
            func.coalesce(
                func.sum(VideoAnalysis.video_duration_seconds),
                0,
            ).label("total_playtime_seconds"),
            func.coalesce(
                func.sum(usage.c.total_tokens),
                0,
            ).label("total_tokens"),
            func.coalesce(
                func.sum(usage.c.cost_usd),
                Decimal("0"),
            ).label("total_cost_usd"),
        )
        .outerjoin(
            usage,
            usage.c.analysis_id == VideoAnalysis.id,
        )
        .where(
            VideoAnalysis.status == "completed",
            VideoAnalysis.processed_at.is_not(None),
            processed_date.between(start_date, end_date),
        )
        .group_by(processed_date)
        .order_by(processed_date)
    )

    result = await db.execute(stmt)

    return [
        DailyDetail(
            date=row.date,
            total_videos=row.total_videos,
            total_playtime_seconds=row.total_playtime_seconds,
            total_tokens=row.total_tokens,
            total_cost_usd=row.total_cost_usd,
        )
        for row in result.all()
    ]


async def _get_today_metrics(
    db: AsyncSession,
    today: date,
    period_start_date: date,
    period_end_date: date,
) -> TodayMetrics:
    usage = _successful_gemini_usage_subquery()

    processed_date = func.date(VideoAnalysis.processed_at)

    today_stmt = (
        select(
            func.count(VideoAnalysis.id).label("total_videos"),
            func.coalesce(
                func.avg(VideoAnalysis.video_duration_seconds),
                0,
            ).label("average_video_runtime_seconds"),
            func.coalesce(
                func.sum(usage.c.total_tokens),
                0,
            ).label("total_tokens"),
            func.coalesce(
                func.sum(usage.c.cost_usd),
                Decimal("0"),
            ).label("total_cost_usd"),
        )
        .outerjoin(
            usage,
            usage.c.analysis_id == VideoAnalysis.id,
        )
        .where(
            VideoAnalysis.status == "completed",
            VideoAnalysis.processed_at.is_not(None),
            processed_date == today,
        )
    )

    today_result = await db.execute(today_stmt)
    today_row = today_result.one()

    total_videos = today_row.total_videos

    if total_videos > 0:
        average_cost = today_row.total_cost_usd / total_videos
        average_tokens = today_row.total_tokens / total_videos
    else:
        average_cost = Decimal("0")
        average_tokens = 0.0

    period_cost_stmt = (
        select(
            func.coalesce(
                func.sum(usage.c.cost_usd),
                Decimal("0"),
            )
        )
        .select_from(VideoAnalysis)
        .outerjoin(
            usage,
            usage.c.analysis_id == VideoAnalysis.id,
        )
        .where(
            VideoAnalysis.status == "completed",
            VideoAnalysis.processed_at.is_not(None),
            processed_date.between(
                period_start_date,
                period_end_date,
            ),
        )
    )

    period_cost_result = await db.execute(period_cost_stmt)
    period_total_cost = period_cost_result.scalar_one()

    return TodayMetrics(
        average_cost_per_video_usd=average_cost,
        average_video_runtime_seconds=float(
            today_row.average_video_runtime_seconds
        ),
        average_token_usage=float(average_tokens),
        period_total_cost_usd=period_total_cost,
    )


async def _get_today_processed_videos(
    db: AsyncSession,
    today: date,
) -> list[ProcessedVideoItem]:
    usage = _successful_gemini_usage_subquery()

    processed_date = func.date(VideoAnalysis.processed_at)

    stmt = (
        select(
            VideoAnalysis.title,
            VideoAnalysis.thumbnail_url,
            VideoAnalysis.video_duration_seconds,
            VideoAnalysis.processed_at,
            func.coalesce(
                usage.c.total_tokens,
                0,
            ).label("total_tokens"),
            func.coalesce(
                usage.c.cost_usd,
                Decimal("0"),
            ).label("cost_usd"),
        )
        .outerjoin(
            usage,
            usage.c.analysis_id == VideoAnalysis.id,
        )
        .where(
            VideoAnalysis.status == "completed",
            VideoAnalysis.processed_at.is_not(None),
            processed_date == today,
        )
        .order_by(VideoAnalysis.processed_at.desc())
    )

    result = await db.execute(stmt)

    return [
        ProcessedVideoItem(
            title=row.title,
            thumbnail_url=row.thumbnail_url,
            total_tokens=row.total_tokens,
            cost_usd=row.cost_usd,
            runtime_seconds=row.video_duration_seconds,
            processed_at=row.processed_at,
        )
        for row in result.all()
    ]


async def get_dashboard(
    db: AsyncSession,
    start_date: date,
    end_date: date,
    today: date,
) -> DashboardResponse:
    overview = await _get_overview(db)

    daily_details = await _get_daily_details(
        db,
        start_date=start_date,
        end_date=end_date,
    )

    today_metrics = await _get_today_metrics(
        db,
        today=today,
        period_start_date=start_date,
        period_end_date=end_date,
    )

    today_processed_videos = await _get_today_processed_videos(
        db,
        today=today,
    )

    daily_token_usage = [
        DailyTokenUsage(
            date=detail.date,
            total_tokens=detail.total_tokens,
        )
        for detail in daily_details
    ]

    return DashboardResponse(
        overview=overview,
        daily_token_usage=daily_token_usage,
        today_metrics=today_metrics,
        daily_details=daily_details,
        today_processed_videos=today_processed_videos,
    )