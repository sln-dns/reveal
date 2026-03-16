from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from idea_check_backend.api.dependencies import get_pair_flow_api_service
from idea_check_backend.api.pair_flow_service import (
    PairFlowApiError,
    PairFlowApiService,
    RunUnavailableError,
    SessionFullError,
)
from idea_check_backend.api.schemas.pair_flow import (
    CreateSessionRequest,
    CreateSessionResponse,
    JoinSessionRequest,
    JoinSessionResponse,
    PairFlowStateResponse,
    SubmitAnswerRequest,
    SubmitAnswerResponse,
)
from idea_check_backend.runtime_service import (
    InvalidAnswerSubmissionError,
    RuntimeFlowError,
    RuntimeNotReadyError,
)

router = APIRouter(prefix="/pair-sessions")
PairFlowApiServiceDependency = Annotated[
    PairFlowApiService,
    Depends(get_pair_flow_api_service),
]


@router.post("", response_model=CreateSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: CreateSessionRequest,
    service: PairFlowApiServiceDependency,
) -> CreateSessionResponse:
    return await service.create_session(display_name=payload.display_name)


@router.post(
    "/{session_id}/join",
    response_model=JoinSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def join_session(
    session_id: str,
    payload: JoinSessionRequest,
    service: PairFlowApiServiceDependency,
) -> JoinSessionResponse:
    try:
        return await service.join_session(session_id, display_name=payload.display_name)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except SessionFullError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except RuntimeNotReadyError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.get(
    "/{session_id}/participants/{participant_id}/state",
    response_model=PairFlowStateResponse,
)
async def get_current_state(
    session_id: str,
    participant_id: str,
    service: PairFlowApiServiceDependency,
) -> PairFlowStateResponse:
    try:
        return await service.get_current_state(session_id, participant_id)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.post(
    "/{session_id}/participants/{participant_id}/answers",
    response_model=SubmitAnswerResponse,
)
async def submit_answer(
    session_id: str,
    participant_id: str,
    payload: SubmitAnswerRequest,
    service: PairFlowApiServiceDependency,
) -> SubmitAnswerResponse:
    try:
        return await service.submit_answer(
            session_id=session_id,
            participant_id=participant_id,
            content_text=payload.content_text,
            content_payload=payload.content_payload,
        )
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except (
        InvalidAnswerSubmissionError,
        PairFlowApiError,
        RuntimeFlowError,
        RunUnavailableError,
        RuntimeNotReadyError,
    ) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
