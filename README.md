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

## MVP Web Client

A minimal browser client is now served by FastAPI at `http://127.0.0.1:8000/client/`.

Local manual flow:

```bash
uv sync --group dev
uv run alembic upgrade head
uv run uvicorn idea_check_backend.main:app --reload
```

Then:

1. Open `http://127.0.0.1:8000/client/`.
2. Create a session in the first tab.
3. Copy the invite link or session ID into a second tab or incognito window.
4. Join as the second participant.
5. Answer each scene in both tabs and watch the client move through `answering`, `waiting`, `reveal`, and `completed`.
6. On the final scene, the client shows the participant-specific summary.

Manual single-page mode for prompt and UX iteration:

1. Open `http://127.0.0.1:8000/client/?mode=manual` or enable `Manual test mode for both players on one page`.
2. Enter optional names for player 1 and player 2.
3. Click `Create dual-player session`.
4. Use the two side-by-side player panels to submit answers independently.
5. Watch the shared scene block, per-player waiting flags, the latest reveal card, and both final summaries on the same page.
6. Expand `Manual raw state` when you need the serialized payload for prompt/debug iteration.

Notes:

- The client is intentionally thin and uses polling against `GET /pair-sessions/{session_id}/participants/{participant_id}/state`.
- Reveal is shown from the answer submission response and mirrored through browser storage so two local tabs can see it during manual testing.
- Manual mode is internal-only and sits on top of the same pair-flow API; the regular single-participant flow at `/client/` still works unchanged.
- The UI also shows the raw serialized pair state to make backend/frontend mismatches obvious during MVP iteration.

## Runtime Observability

Pair flow now emits structured runtime events through the standard Python `logging` stack with a JSON formatter. The event catalog and payload schema are documented in [docs/runtime_event_logging.md](/var/folders/42/jpgf43_12bzf43rnsrfg2r800000gn/T/vibe-kanban/worktrees/1155-runtime-event-lo/Idea_check/docs/runtime_event_logging.md).

Current domain events include:

- `session_created`
- `participant_joined`
- `scenario_run_started`
- `scene_activated`
- `question_delivered`
- `answer_submitted`
- `waiting_for_second_answer`
- `answers_revealed`
- `scene_completed`
- `branch_selected`
- `run_completed`
- `runtime_error`

## LLM configuration

User-facing generation layer works in Russian only: scene intros, questions, transitions, fallback texts, and final summaries must be generated in natural Russian without mixing in English labels.

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
Automated smoke tests clear `AI_*` env vars and must not depend on a developer-local provider config.
Successful smoke output is expected to be fully Russian in all user-facing fields.

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
