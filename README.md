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
```

## Structure

- `src/idea_check_backend/api` - HTTP routes
- `src/idea_check_backend/scenario_engine` - scenario orchestration layer
- `src/idea_check_backend/llm_service` - LLM integration facade
- `src/idea_check_backend/persistence` - persistence abstractions
- `src/idea_check_backend/shared_types` - shared DTOs and settings
- `docs/mvp_data_model.md` - runtime data model overview for MVP
