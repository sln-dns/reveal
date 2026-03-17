from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from idea_check_backend.api.dependencies import get_pair_flow_api_service
from idea_check_backend.api.pair_flow_service import PairFlowApiService
from idea_check_backend.main import create_app
from idea_check_backend.persistence.db import make_async_engine
from idea_check_backend.persistence.models import Base
from idea_check_backend.persistence.repository import SqlAlchemyScenarioRuntimeRepository
from idea_check_backend.runtime_service import PairScenarioRuntimeService
from idea_check_backend.scenario_engine.blueprint_loader import ScenarioBlueprintRepository

BLUEPRINT_PATH = Path(__file__).resolve().parents[1] / "scenario_blueprint.date_route.json"


def test_pair_flow_api_happy_path(tmp_path: Path) -> None:
    service = asyncio.run(_make_service(tmp_path / "pair_flow_api.db"))
    app = create_app()
    app.dependency_overrides[get_pair_flow_api_service] = lambda: service
    client = TestClient(app)

    create_response = client.post("/pair-sessions", json={"display_name": "Alex"})

    assert create_response.status_code == 201
    create_payload = create_response.json()
    session_id = create_payload["state"]["session"]["id"]
    participant_a_id = create_payload["access"]["id"]
    assert create_payload["state"]["state_kind"] == "waiting"
    assert create_payload["state"]["run"] is None
    assert create_payload["state"]["answered_current_question"] is False

    join_response = client.post(
        f"/pair-sessions/{session_id}/join",
        json={"display_name": "Sam"},
    )

    assert join_response.status_code == 201
    join_payload = join_response.json()
    participant_b_id = join_payload["access"]["id"]
    run_id = join_payload["state"]["run"]["id"]
    assert join_payload["state"]["state_kind"] == "answering"
    assert join_payload["state"]["run"]["current_scene_key"] == "scene_01_intro"
    assert (
        join_payload["state"]["current_scene"]["questions"][1]["participant_id"]
        == participant_b_id
    )

    state_response = client.get(
        f"/pair-sessions/{session_id}/participants/{participant_a_id}/state"
    )

    assert state_response.status_code == 200
    state_payload = state_response.json()
    assert state_payload["run"]["id"] == run_id
    assert state_payload["state_kind"] == "answering"
    assert state_payload["current_scene"]["key"] == "scene_01_intro"

    first_submit_response = client.post(
        f"/pair-sessions/{session_id}/participants/{participant_a_id}/answers",
        json={"content_text": "Quiet cafe"},
    )

    assert first_submit_response.status_code == 200
    first_submit_payload = first_submit_response.json()
    assert first_submit_payload["outcome"] == "waiting"
    assert first_submit_payload["state"]["state_kind"] == "waiting"
    assert first_submit_payload["state"]["answered_current_question"] is True
    assert first_submit_payload["state"]["can_reveal"] is False
    assert first_submit_payload["reveal"] is None

    second_submit_response = client.post(
        f"/pair-sessions/{session_id}/participants/{participant_b_id}/answers",
        json={"content_text": "Riverside walk"},
    )

    assert second_submit_response.status_code == 200
    second_submit_payload = second_submit_response.json()
    assert second_submit_payload["outcome"] == "progressed"
    assert second_submit_payload["advanced_to_next_scene"] is True
    assert second_submit_payload["run_completed"] is False
    assert second_submit_payload["state"]["state_kind"] == "answering"
    assert second_submit_payload["state"]["current_scene"]["key"] == "scene_02_direction"
    assert second_submit_payload["reveal"]["key"] == "scene_01_intro"
    assert [item["answer_text"] for item in second_submit_payload["reveal"]["questions"]] == [
        "Quiet cafe",
        "Riverside walk",
    ]


def test_pair_flow_api_rejects_join_when_session_is_full(tmp_path: Path) -> None:
    service = asyncio.run(_make_service(tmp_path / "pair_flow_api_full.db"))
    app = create_app()
    app.dependency_overrides[get_pair_flow_api_service] = lambda: service
    client = TestClient(app)

    session_id = client.post("/pair-sessions", json={}).json()["state"]["session"]["id"]
    join_one = client.post(f"/pair-sessions/{session_id}/join", json={"display_name": "Sam"})

    assert join_one.status_code == 201

    join_two = client.post(f"/pair-sessions/{session_id}/join", json={"display_name": "Taylor"})

    assert join_two.status_code == 409
    assert "already has 2 participants" in join_two.json()["detail"]


def test_pair_flow_api_rejects_duplicate_submit_answer(tmp_path: Path) -> None:
    service = asyncio.run(_make_service(tmp_path / "pair_flow_api_duplicate.db"))
    app = create_app()
    app.dependency_overrides[get_pair_flow_api_service] = lambda: service
    client = TestClient(app)

    create_payload = client.post("/pair-sessions", json={}).json()
    session_id = create_payload["state"]["session"]["id"]
    participant_a_id = create_payload["access"]["id"]
    client.post(f"/pair-sessions/{session_id}/join", json={})

    first_submit = client.post(
        f"/pair-sessions/{session_id}/participants/{participant_a_id}/answers",
        json={"content_text": "First answer"},
    )

    assert first_submit.status_code == 200

    duplicate_submit = client.post(
        f"/pair-sessions/{session_id}/participants/{participant_a_id}/answers",
        json={"content_text": "Duplicate answer"},
    )

    assert duplicate_submit.status_code == 409
    assert "already answered" in duplicate_submit.json()["detail"]


def test_pair_flow_api_returns_final_summary_after_run_completion(tmp_path: Path) -> None:
    service = asyncio.run(_make_service(tmp_path / "pair_flow_api_summary.db"))
    app = create_app()
    app.dependency_overrides[get_pair_flow_api_service] = lambda: service
    client = TestClient(app)

    create_payload = client.post("/pair-sessions", json={"display_name": "Alex"}).json()
    session_id = create_payload["state"]["session"]["id"]
    participant_a_id = create_payload["access"]["id"]
    join_payload = client.post(
        f"/pair-sessions/{session_id}/join",
        json={"display_name": "Sam"},
    ).json()
    participant_b_id = join_payload["access"]["id"]

    state_payload = join_payload["state"]
    assert state_payload["final_summary"] is None

    while not state_payload["completed"]:
        scene_key = state_payload["current_scene"]["key"]
        client.post(
            f"/pair-sessions/{session_id}/participants/{participant_a_id}/answers",
            json={"content_text": f"{scene_key} quiet cafe and long walk"},
        )
        result = client.post(
            f"/pair-sessions/{session_id}/participants/{participant_b_id}/answers",
            json={"content_text": f"{scene_key} playful adventure and jokes"},
        )
        assert result.status_code == 200
        state_payload = result.json()["state"]

    assert state_payload["completed"] is True
    assert state_payload["state_kind"] == "completed"
    assert state_payload["current_scene"] is None
    assert state_payload["final_summary"] is not None
    assert state_payload["final_summary"]["recipient_participant_id"] == participant_b_id
    assert state_payload["final_summary"]["subject_participant_id"] == participant_a_id
    assert state_payload["final_summary"]["focus"] == [
        "other_person_preferences",
        "other_person_vibe",
        "conversation_topics_for_real_meeting",
    ]
    assert state_payload["final_summary"]["tone"] == "warm_observational"
    assert "V realnom razgovore mozhno prodolzhit" in state_payload["final_summary"]["text"]

    participant_a_state = client.get(
        f"/pair-sessions/{session_id}/participants/{participant_a_id}/state"
    )
    assert participant_a_state.status_code == 200
    participant_a_payload = participant_a_state.json()
    assert participant_a_payload["final_summary"] is not None
    assert participant_a_payload["final_summary"]["recipient_participant_id"] == participant_a_id
    assert participant_a_payload["final_summary"]["subject_participant_id"] == participant_b_id


async def _make_service(db_path: Path) -> PairFlowApiService:
    engine = make_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    repository = SqlAlchemyScenarioRuntimeRepository(session_factory)
    blueprints = ScenarioBlueprintRepository({"date_route": BLUEPRINT_PATH})
    runtime_service = PairScenarioRuntimeService(repository, blueprints)
    return PairFlowApiService(
        repository=repository,
        runtime_service=runtime_service,
        blueprint_repository=blueprints,
    )
