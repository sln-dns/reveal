# Architecture Tech Stack

Этот файл фиксирует рекомендуемый технический стек проекта по слоям, с прицелом на MVP и дальнейшее развитие.

## Stack principles

- Стек должен быть быстрым для старта, а не "идеальным в вакууме".
- Нужно минимизировать количество разных языков и платформ.
- Нужно хорошо поддерживать stateful backend, JSON-driven scenario engine и LLM integration.
- Нужно сразу предусмотреть нормальное логгирование и наблюдаемость.
- Python-часть проекта стоит строить через `uv`.

## Recommended overall stack

### Frontend

- `TypeScript`
- `Next.js`
- `React`
- `Tailwind CSS`

Почему:

- быстрый старт для веб-продукта;
- удобно собирать link-based flows;
- легко делать SSR/CSR-гибрид;
- TypeScript хорошо подходит для shared contracts с API;
- React подходит для stateful UI и асинхронных экранов ожидания.

### Backend

- `Python`
- `FastAPI`
- `Pydantic`
- `uv`

Почему:

- Python естественно ложится на scenario engine и LLM integration;
- FastAPI даёт быстрый и понятный API-слой;
- Pydantic хорошо подходит для валидации JSON blueprints, runtime state и generation payloads;
- `uv` даёт хороший DX для зависимостей, lockfile и запуска.

### Database

- `PostgreSQL`
- `SQLAlchemy` 2.x
- `Alembic`

Почему:

- нужен надёжный stateful storage;
- хорошо хранит session state, answers, logs, summaries;
- SQLAlchemy подходит для постепенного роста модели;
- Alembic нужен для миграций.

### Cache / ephemeral coordination

- `Redis`

Почему:

- удобно для короткоживущих состояний;
- подойдёт для rate limiting, background coordination, notification scheduling;
- поможет, если появятся real-time элементы и очереди.

### Background jobs

- `RQ` или `Arq`

Предпочтение:

- для Python-first MVP я бы смотрел на `Arq`, если хочется async-friendly подход;
- если нужен более простой и понятный старт, можно взять `RQ`.

Почему нужен job layer:

- отправка уведомлений;
- generation tasks;
- retries;
- delayed reminders;
- summary generation after scene completion.

### LLM integration

- `OpenAI API`
- отдельный внутренний `llm-service` модуль
- строгие Pydantic-схемы для входа и выхода

Почему:

- генерацию лучше централизовать в одном слое;
- удобно логгировать prompts, responses, retries и fallback;
- легче позже заменить модель, если потребуется.

### Logging and observability

- структурированные JSON-логи через стандартный Python logging или `structlog`
- `Logfire` или `Sentry`
- `Prometheus` + `Grafana` позже, если понадобится

Предпочтение для MVP:

- `structlog` для событийных логов;
- `Sentry` для ошибок и traces;
- отдельная таблица продуктовых событий в PostgreSQL;
- при росте добавить метрики и dashboard.

### Notifications

- e-mail: `Resend` или `Postmark`
- in-app notifications через backend state

Позже:

- web push;
- Telegram bot;
- мобильные push-каналы, если появится приложение.

### Auth / session access

- для MVP: magic link или guest session tokens
- позже: полноценный auth provider, если появится потребность

Почему:

- у продукта должен быть очень низкий порог входа;
- тяжёлый auth на старте может убить conversion.

## Layer-by-layer recommendation

### 1. Web client

Рекомендуемый стек:

- `Next.js`
- `React`
- `TypeScript`
- `Tailwind CSS`
- `TanStack Query`
- `Zod` для клиентской валидации и shared parsing при необходимости

Что это даст:

- хороший UX для асинхронных экранов;
- удобную загрузку состояния сессии;
- простую реализацию invite pages, waiting screens, summary pages;
- хорошую основу под future design system.

### 2. API layer

Рекомендуемый стек:

- `FastAPI`
- `Pydantic`
- OpenAPI из коробки

Что это даст:

- быстрое описание routes;
- понятную сериализацию данных;
- валидацию входных и выходных контрактов;
- удобную основу для фронтенда и админских инструментов.

### 3. Scenario engine

Рекомендуемый стек:

- `Python`
- `Pydantic` models для blueprint и runtime state
- чистые domain services без привязки к web framework

Что важно:

- scenario engine должен быть обычным Python-модулем;
- он не должен зависеть от FastAPI напрямую;
- blueprint JSON должен валидироваться через строгие модели;
- branching и scene progression должны быть детерминированы.

### 4. LLM service

Рекомендуемый стек:

- `Python`
- отдельный service module
- `OpenAI API`
- Pydantic output parsing / post-validation

Что важно:

- не смешивать промпты с API handlers;
- держать prompt builders отдельно;
- иметь fallback-логику и re-try policy;
- логгировать каждый generation call.

### 5. Persistence

Рекомендуемый стек:

- `PostgreSQL`
- `SQLAlchemy` 2.x
- `Alembic`

Что важно:

- отдельно хранить blueprint, run state и generated content;
- иметь явные таблицы для ответов, reveal events, generation logs;
- не пытаться на старте утащить всё в JSONB без структуры.

### 6. Background jobs and notifications

Рекомендуемый стек:

- `Redis`
- `Arq` или `RQ`
- `Resend` или `Postmark`

Что важно:

- reminders и delayed actions должны жить вне request/response;
- notification sending должен быть retriable;
- generation tasks в ряде случаев лучше выносить в background.

### 7. Logging and observability

Рекомендуемый стек:

- `structlog`
- `Sentry`
- продуктовые события в PostgreSQL

Что важно:

- разделить технические ошибки и продуктовые события;
- логгировать transitions сценария;
- логгировать LLM payload metadata;
- собирать completion и stuck metrics с самого начала.

## Recommended repository shape

Если проект будет монорепой, логично видеть структуру примерно так:

```text
/
  apps/
    web/
    api/
  packages/
    scenario_engine/
    llm_service/
    shared_types/
  infra/
  docs/
```

Если проект хочется держать проще на старте, можно начать даже так:

```text
/
  web/
  backend/
  docs/
```

И уже внутри `backend/` разделить доменные модули.

## Python toolchain

Так как ты любишь `uv`, я бы рекомендовал следующий базовый набор:

- `uv` для зависимостей и lockfile
- `uv run` для запуска локальных команд
- `pytest` для тестов
- `ruff` для lint и formatting
- `mypy` позже, если типизация станет мешать ошибкам в engine logic

Практически это означает:

- backend и domain logic лучше держать как Python-проект под `uv`;
- отдельные команды для API, workers, tests и migrations тоже запускать через `uv`.

## Frontend toolchain

- `pnpm`
- `Next.js`
- `TypeScript`
- `ESLint`
- `Prettier`

Если захочется уменьшить количество пакетных менеджеров, это нормально не получится: для фронтенда всё равно удобнее отдельный JS toolchain.

## MVP recommendation

Для первой реализации я бы взял именно такой стек:

- frontend: `Next.js + TypeScript + Tailwind`
- backend: `Python + FastAPI + Pydantic + uv`
- database: `PostgreSQL`
- cache/jobs: `Redis + Arq`
- LLM: `OpenAI API`
- logging: `structlog + Sentry`
- email: `Resend`

Это выглядит достаточно современно, быстро в разработке и без лишней сложности.

## What not to overcomplicate early

- не выделять отдельные микросервисы;
- не строить event bus раньше времени;
- не добавлять Kafka, Temporal и подобные тяжёлые штуки;
- не уводить сценарный движок в слишком абстрактный framework;
- не переусложнять real-time слой, пока core loop асинхронный.

## Suggested future upgrades

Когда продукт упрётся в рост, можно думать про:

- выделение worker pool отдельно;
- отдельный analytics store;
- feature flags;
- A/B testing для сценариев;
- dashboard для сценарных blueprint и quality review;
- более сложный prompt orchestration layer.
