from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    gemini_api_key: str
    gemini_model: str = "gemini-3.6-flash"

    redis_url: str

    tester_keys: str

    daily_user_limit: int = 10
    daily_global_limit: int = 50

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def tester_key_set(self) -> set[str]:
        return {
            key.strip()
            for key in self.tester_keys.split(",")
            if key.strip()
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()