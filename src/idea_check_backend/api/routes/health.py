from fastapi import APIRouter

from idea_check_backend.shared_types.health import HealthCheckResponse
from idea_check_backend.shared_types.settings import get_settings

router = APIRouter()


@router.get("/health", response_model=HealthCheckResponse)
def healthcheck() -> HealthCheckResponse:
    settings = get_settings()
    return HealthCheckResponse(status="ok", environment=settings.app_env)
