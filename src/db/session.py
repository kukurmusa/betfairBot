"""Synchronous database session management.

Uses SQLAlchemy 2.0 with psycopg2 driver.
Engine is a module-level singleton to avoid creating multiple connection pools.
"""

from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

_engine: Engine | None = None


def get_engine(database_url: str) -> Engine:
    """Return the singleton engine, creating it on first call."""
    global _engine
    if _engine is None:
        _engine = create_engine(database_url, echo=False, pool_size=5, max_overflow=2)
    return _engine


def get_session(database_url: str) -> Session:
    """Create and return a new database session."""
    factory = sessionmaker(get_engine(database_url), expire_on_commit=False)
    return factory()


def dispose_engine() -> None:
    """Dispose the engine and close all connections."""
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None
