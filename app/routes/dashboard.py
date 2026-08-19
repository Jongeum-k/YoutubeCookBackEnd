# app/routes/dashboard.py

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_tester_key
from app.db.session import get_db
from app.schemas.dashboard import DashboardResponse
from app.services.dashboard import get_dashboard


router = APIRouter(
    prefix="/dashboard",
    tags=["dashboard"],
)


@router.get(
    "",
    response_model=DashboardResponse,
)
async def read_dashboard(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[str, Depends(verify_tester_key)],
    start_date: Annotated[
        date | None,
        Query(description="Start date of dashboard period"),
    ] = None,
    end_date: Annotated[
        date | None,
        Query(description="End date of dashboard period"),
    ] = None,
):
    today = date.today()

    if start_date is None and end_date is None:
        end_date = today
        start_date = today - timedelta(days=3)

    elif start_date is None:
        start_date = end_date - timedelta(days=3)

    elif end_date is None:
        end_date = today

    if start_date > end_date:
        raise HTTPException(
            status_code=422,
            detail="start_date must be earlier than or equal to end_date",
        )

    return await get_dashboard(
        db=db,
        start_date=start_date,
        end_date=end_date,
        today=today,
    )