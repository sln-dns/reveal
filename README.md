# Idea Check Backend

Minimal backend skeleton on Python, FastAPI, and uv.

## Requirements

- `uv`
- Python `3.14` (see `.python-version`)

## Quick start

```bash
uv sync --group dev
cp .env.example .env
uv run uvicorn idea_check_backend.main:app --reload
```

Service will be available on `http://127.0.0.1:8000`.

## Commands

```bash
uv run alembic upgrade head
uv run ruff check .
uv run pytest
uv run idea-check-smoke-generate
```

## Pair Flow API

Minimal product-facing pair runtime endpoints:

```bash
POST /pair-sessions
POST /pair-sessions/{session_id}/join
GET /pair-sessions/{session_id}/participants/{participant_id}/state
POST /pair-sessions/{session_id}/participants/{participant_id}/answers
```

Expected local flow:

```bash
uv run alembic upgrade head
uv run uvicorn idea_check_backend.main:app --reload
```

The API is a thin layer over `PairScenarioRuntimeService`: session creation creates the first participant, second participant join starts the runtime run, `state` returns a frontend-ready current view, and answer submission returns `waiting`, `progressed`, or `completed` outcomes with reveal data when both answers are available.

## LLM configuration

Set provider access through env vars:

```bash
AI_MODEL=gpt-4.1-mini
AI_PROVIDER_API_KEY=your-provider-key
AI_PROVIDER_URL=https://api.openai.com/v1/responses
```

Supported request formats are selected from the URL path:

- `/responses` -> `{"model", "input"}`
- `/chat/completions` -> `{"model", "messages"}`
- `/completions` -> `{"model", "prompt"}`

## Smoke generation

Manual smoke flow uses the real AI provider from `.env` and is not part of the default test suite.

```bash
uv run idea-check-smoke-generate
```

Optional flags:

```bash
uv run idea-check-smoke-generate --scene-id scene_01_intro
uv run idea-check-smoke-generate --output-dir artifacts/smoke_generation
```

Requirements before running:

- `AI_MODEL`
- `AI_PROVIDER_API_KEY`
- `AI_PROVIDER_URL`

The command fails fast on missing config, network/provider errors, or any provider response that falls back to stub output. Successful runs save both `result.json` and `result.md` under `artifacts/smoke_generation/...` for review.

## Structure

- `src/idea_check_backend/api` - HTTP routes
- `src/idea_check_backend/scenario_engine` - scenario orchestration layer
- `src/idea_check_backend/llm_service` - LLM integration facade
- `src/idea_check_backend/persistence` - persistence abstractions
- `src/idea_check_backend/shared_types` - shared DTOs and settings
- `docs/mvp_data_model.md` - runtime data model overview for MVP
