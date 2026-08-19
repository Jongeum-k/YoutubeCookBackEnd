from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class DashboardOverview(BaseModel):
    total_videos: int
    total_playtime_seconds: int
    total_tokens: int
    total_cost_usd: Decimal


class DailyTokenUsage(BaseModel):
    date: date
    total_tokens: int


class TodayMetrics(BaseModel):
    average_cost_per_video_usd: Decimal
    average_video_runtime_seconds: float
    average_token_usage: float
    period_total_cost_usd: Decimal


class DailyDetail(BaseModel):
    date: date
    total_videos: int
    total_playtime_seconds: int
    total_tokens: int
    total_cost_usd: Decimal


class ProcessedVideoItem(BaseModel):
    title: str | None
    thumbnail_url: str | None
    total_tokens: int
    cost_usd: Decimal
    runtime_seconds: int | None
    processed_at: datetime


class DashboardResponse(BaseModel):
    overview: DashboardOverview
    daily_token_usage: list[DailyTokenUsage]
    today_metrics: TodayMetrics
    daily_details: list[DailyDetail]
    today_processed_videos: list[ProcessedVideoItem]