from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from idea_check_backend.api.router import api_router
from idea_check_backend.observability.runtime_events import configure_logging
from idea_check_backend.shared_types.settings import get_settings

WEB_CLIENT_DIR = Path(__file__).resolve().parent / "web_client"


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging()
    app = FastAPI(title=settings.app_name)
    app.include_router(api_router)
    if WEB_CLIENT_DIR.exists():
        app.mount("/client", StaticFiles(directory=WEB_CLIENT_DIR, html=True), name="client")

        @app.get("/", include_in_schema=False)
        async def root() -> RedirectResponse:
            return RedirectResponse(url="/client/")

    return app


app = create_app()
