from fastapi import APIRouter

from idea_check_backend.api.routes.health import router as health_router
from idea_check_backend.api.routes.pair_flow import router as pair_flow_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
api_router.include_router(pair_flow_router, tags=["pair-flow"])
