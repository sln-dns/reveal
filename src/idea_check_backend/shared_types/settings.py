from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "local"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    app_name: str = "Idea Check Backend"
    database_url: str = "sqlite+aiosqlite:///./idea_check.db"
    llm_provider: str = "stub"
    llm_model: str = "gpt-4.1-mini"
    llm_timeout_seconds: float = 15.0
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1/responses"

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_prefix="",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
