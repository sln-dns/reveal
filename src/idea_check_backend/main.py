from fastapi import FastAPI

from idea_check_backend.api.router import api_router
from idea_check_backend.observability.runtime_events import configure_logging
from idea_check_backend.shared_types.settings import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging()
    app = FastAPI(title=settings.app_name)
    app.include_router(api_router)
    return app


app = create_app()
