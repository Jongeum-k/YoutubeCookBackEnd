# app/core/security.py

from fastapi import Header, HTTPException, status

from app.core.config import settings


async def verify_tester_key(
    x_tester_key: str | None = Header(
        default=None,
        alias="X-Tester-Key",
    ),
) -> str:
    if not x_tester_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tester key is required",
        )

    if x_tester_key not in settings.tester_keys:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid tester key",
        )

    return x_tester_key