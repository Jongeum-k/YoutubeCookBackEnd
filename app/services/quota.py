# app/services/quota.py

from datetime import datetime, timezone
from uuid import uuid4

from redis.asyncio import Redis

from app.core.config import get_settings
from app.dtos.quota import QuotaReservation


class QuotaExceededError(Exception):
    pass


class InvalidTesterKeyError(Exception):
    pass


class QuotaService:
    USAGE_TTL_SECONDS = 60 * 60 * 25
    RESERVATION_TTL_SECONDS = 60 * 30

    _RESERVE_SCRIPT = """
    local tester_count = tonumber(redis.call("GET", KEYS[1]) or "0")
    local global_count = tonumber(redis.call("GET", KEYS[2]) or "0")

    local tester_limit = tonumber(ARGV[1])
    local global_limit = tonumber(ARGV[2])
    local usage_ttl = tonumber(ARGV[3])
    local reservation_ttl = tonumber(ARGV[4])

    if tester_count >= tester_limit then
        return {-1, tester_count, global_count}
    end

    if global_count >= global_limit then
        return {-2, tester_count, global_count}
    end

    tester_count = redis.call("INCR", KEYS[1])
    redis.call("EXPIRE", KEYS[1], usage_ttl)

    global_count = redis.call("INCR", KEYS[2])
    redis.call("EXPIRE", KEYS[2], usage_ttl)

    redis.call(
        "SET",
        KEYS[3],
        "reserved",
        "EX",
        reservation_ttl
    )

    return {1, tester_count, global_count}
    """

    _COMMIT_SCRIPT = """
    if redis.call("GET", KEYS[1]) ~= "reserved" then
        return 0
    end

    redis.call("DEL", KEYS[1])

    return 1
    """

    _ROLLBACK_SCRIPT = """
    if redis.call("GET", KEYS[3]) ~= "reserved" then
        return 0
    end

    local tester_count = tonumber(redis.call("GET", KEYS[1]) or "0")
    local global_count = tonumber(redis.call("GET", KEYS[2]) or "0")

    if tester_count > 0 then
        redis.call("DECR", KEYS[1])
    end

    if global_count > 0 then
        redis.call("DECR", KEYS[2])
    end

    redis.call("DEL", KEYS[3])

    return 1
    """

    def __init__(self, redis: Redis) -> None:
        self.redis = redis
        self.settings = get_settings()

    def validate_tester(self, tester_key: str) -> None:
        if tester_key not in self.settings.tester_key_set:
            raise InvalidTesterKeyError()

    def _build_keys(
        self,
        *,
        tester_key: str,
        quota_date: str,
        reservation_id: str,
    ) -> tuple[str, str, str]:
        tester_usage_key = (
            f"quota:tester:{tester_key}:{quota_date}"
        )
        global_usage_key = (
            f"quota:global:{quota_date}"
        )
        reservation_key = (
            f"quota:reservation:{reservation_id}"
        )

        return (
            tester_usage_key,
            global_usage_key,
            reservation_key,
        )

    async def reserve(
        self,
        tester_key: str,
    ) -> QuotaReservation:
        self.validate_tester(tester_key)

        reservation_id = str(uuid4())
        quota_date = datetime.now(timezone.utc).date().isoformat()

        (
            tester_usage_key,
            global_usage_key,
            reservation_key,
        ) = self._build_keys(
            tester_key=tester_key,
            reservation_id=reservation_id,
            quota_date=quota_date
        )

        result = await self.redis.eval(
            self._RESERVE_SCRIPT,
            3,
            tester_usage_key,
            global_usage_key,
            reservation_key,
            self.settings.daily_user_limit,
            self.settings.daily_global_limit,
            self.USAGE_TTL_SECONDS,
            self.RESERVATION_TTL_SECONDS,
        )

        status = int(result[0])
        tester_count = int(result[1])
        global_count = int(result[2])

        if status == -1:
            raise QuotaExceededError(
                "Daily tester quota exceeded."
            )

        if status == -2:
            raise QuotaExceededError(
                "Daily global quota exceeded."
            )

        return QuotaReservation(
            reservation_id=reservation_id,
            tester_key=tester_key,
            quota_date=quota_date,
            tester_count=tester_count,
            global_count=global_count,
        )

    async def commit(
            self,
            reservation: QuotaReservation,
    ) -> None:
        (
            _,
            _,
            reservation_key,
        ) = self._build_keys(
            tester_key=reservation.tester_key,
            quota_date=reservation.quota_date,
            reservation_id=reservation.reservation_id,
        )

        await self.redis.eval(
            self._COMMIT_SCRIPT,
            1,
            reservation_key,
        )

    async def rollback(
            self,
            reservation: QuotaReservation,
    ) -> None:
        (
            tester_usage_key,
            global_usage_key,
            reservation_key,
        ) = self._build_keys(
            tester_key=reservation.tester_key,
            quota_date=reservation.quota_date,
            reservation_id=reservation.reservation_id,
        )

        await self.redis.eval(
            self._ROLLBACK_SCRIPT,
            3,
            tester_usage_key,
            global_usage_key,
            reservation_key,
        )