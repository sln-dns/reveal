from __future__ import annotations

from functools import lru_cache

from idea_check_backend.api.pair_flow_service import PairFlowApiService
from idea_check_backend.persistence.db import make_session_factory
from idea_check_backend.persistence.repository import SqlAlchemyScenarioRuntimeRepository
from idea_check_backend.runtime_service import PairScenarioRuntimeService
from idea_check_backend.scenario_engine.blueprint_loader import ScenarioBlueprintRepository


@lru_cache
def _get_runtime_repository() -> SqlAlchemyScenarioRuntimeRepository:
    return SqlAlchemyScenarioRuntimeRepository(make_session_factory())


@lru_cache
def _get_blueprint_repository() -> ScenarioBlueprintRepository:
    return ScenarioBlueprintRepository()


@lru_cache
def get_pair_flow_api_service() -> PairFlowApiService:
    repository = _get_runtime_repository()
    runtime_service = PairScenarioRuntimeService(repository, _get_blueprint_repository())
    return PairFlowApiService(
        repository=repository,
        runtime_service=runtime_service,
        blueprint_repository=_get_blueprint_repository(),
    )
