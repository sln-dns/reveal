from functools import lru_cache
from urllib.parse import urlparse

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "local"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    app_name: str = "Idea Check Backend"
    database_url: str = "sqlite+aiosqlite:///./idea_check.db"
    ai_model: str = Field(default="gpt-4.1-mini", alias="AI_MODEL")
    ai_provider_api_key: str | None = Field(default=None, alias="AI_PROVIDER_API_KEY")
    ai_provider_url: str | None = Field(default=None, alias="AI_PROVIDER_URL")
    llm_timeout_seconds: float = 15.0

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_prefix="",
        extra="ignore",
        populate_by_name=True,
    )

    @property
    def llm_model(self) -> str:
        return self.ai_model

    @property
    def llm_provider(self) -> str:
        if not self.ai_provider_url:
            return "stub"
        parsed = urlparse(self.ai_provider_url)
        return parsed.netloc or "generic_http"


@lru_cache
def get_settings() -> Settings:
    return Settings()
