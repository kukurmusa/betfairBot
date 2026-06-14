"""Alembic environment configuration.

Uses the synchronous ``DATABASE_URL_SYNC`` env var (psycopg2) for
running migrations.  The bot uses asyncpg at runtime; Alembic cannot
use asyncpg, so a separate sync URL is required.

Reads ``Base.metadata`` from ``src.db.models`` so ``--autogenerate``
works correctly.
"""

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool
from dotenv import load_dotenv

# Ensure repo root is on sys.path so we can import src.*
_repo_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_repo_root))

load_dotenv()

from src.db.models import Base  # noqa: E402

config = context.config

# Prefer DATABASE_URL_SYNC from .env; fall back to alembic.ini
sync_url = os.getenv("DATABASE_URL_SYNC")
if sync_url:
    config.set_main_option("sqlalchemy.url", sync_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without connecting)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        version_table_schema="trading",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations with a synchronous psycopg2 engine."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            version_table_schema="trading",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
