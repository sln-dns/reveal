from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from idea_check_backend.shared_types.settings import get_settings


def make_async_engine(database_url: str | None = None) -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(database_url or settings.database_url, future=True)


def make_session_factory(database_url: str | None = None) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(make_async_engine(database_url), expire_on_commit=False)


def make_sync_database_url(database_url: str | None = None) -> str:
    settings = get_settings()
    url = make_url(database_url or settings.database_url)
    if url.drivername == "sqlite+aiosqlite":
        return str(url.set(drivername="sqlite"))
    return str(url)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    session_factory = make_session_factory()
    async with session_factory() as session:
        yield session
