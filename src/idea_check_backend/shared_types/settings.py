from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "local"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    app_name: str = "Idea Check Backend"
    database_url: str = "sqlite+aiosqlite:///./idea_check.db"

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_prefix="",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
