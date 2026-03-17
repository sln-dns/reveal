from __future__ import annotations

import pytest

from idea_check_backend.shared_types.settings import get_settings


@pytest.fixture(autouse=True)
def isolate_ai_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests independent from developer-local AI provider configuration."""

    get_settings.cache_clear()
    for env_name in ("AI_MODEL", "AI_PROVIDER_API_KEY", "AI_PROVIDER_URL"):
        monkeypatch.delenv(env_name, raising=False)
    yield
    get_settings.cache_clear()
