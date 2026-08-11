from datetime import datetime, timezone

from redis.asyncio import Redis

from app.core.config import get_settings


class QuotaExceededError(Exception):
    pass


class InvalidTesterKeyError(Exception):
    pass


class QuotaService:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis
        self.settings = get_settings()

    def validate_tester(self, tester_key: str) -> None:
        if tester_key not in self.settings.tester_key_set:
            raise InvalidTesterKeyError()

    async def consume(self, tester_key: str) -> tuple[int, int]:
        self.validate_tester(tester_key)

        today = datetime.now(timezone.utc).date().isoformat()

        tester_usage_key = f"quota:tester:{tester_key}:{today}"
        global_usage_key = f"quota:global:{today}"

        tester_usage = await self.redis.get(tester_usage_key)
        global_usage = await self.redis.get(global_usage_key)

        tester_count = int(tester_usage or 0)
        global_count = int(global_usage or 0)

        if tester_count >= self.settings.daily_user_limit:
            raise QuotaExceededError(
                "Daily tester quota exceeded."
            )

        if global_count >= self.settings.daily_global_limit:
            raise QuotaExceededError(
                "Daily global quota exceeded."
            )

        pipe = self.redis.pipeline()

        pipe.incr(tester_usage_key)
        pipe.expire(tester_usage_key, 60 * 60 * 25)

        pipe.incr(global_usage_key)
        pipe.expire(global_usage_key, 60 * 60 * 25)

        results = await pipe.execute()

        new_tester_count = results[0]
        new_global_count = results[2]

        return new_tester_count, new_global_count