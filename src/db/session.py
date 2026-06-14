"""Async database session management.

Uses SQLAlchemy 2.0 async engine with asyncpg driver.
The engine is a module-level singleton to avoid creating
multiple connection pools.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_engine: AsyncEngine | None = None


def get_engine(database_url: str) -> AsyncEngine:
    """Return the singleton async engine, creating it on first call.

    Args:
        database_url: PostgreSQL connection URL (asyncpg dialect).

    Returns:
        The async engine instance.
    """
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            database_url,
            echo=False,
            pool_size=5,
            max_overflow=2,
        )
    return _engine


def create_session_factory(
    database_url: str,
) -> async_sessionmaker[AsyncSession]:
    """Create an async session factory.

    Args:
        database_url: PostgreSQL connection URL.

    Returns:
        A callable that yields new AsyncSession instances.
    """
    engine = get_engine(database_url)
    return async_sessionmaker(engine, expire_on_commit=False)


async def dispose_engine() -> None:
    """Dispose the engine and close all connections."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
