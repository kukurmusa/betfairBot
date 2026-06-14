"""Async sanity check — verifies Postgres is up and all tables exist.

Uses asyncpg (same driver as the bot).  Run after ``docker compose up``
and ``alembic upgrade head`` to confirm infrastructure is ready.

Usage::

    python scripts/db_check.py
"""

import asyncio
import os
import sys

import asyncpg
from dotenv import load_dotenv

load_dotenv()

EXPECTED_TABLES = ["runs", "markets", "ticks", "orders", "trades"]


async def main() -> None:
    """Connect to Postgres and verify all expected tables exist."""
    # asyncpg uses the raw postgresql:// URL, not postgresql+asyncpg://
    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://bot:bot_password@localhost:5432/betfair_ltd",
    )
    raw_url = database_url.replace("postgresql+asyncpg://", "postgresql://")

    try:
        conn = await asyncpg.connect(raw_url)
        print(f"✓ Connected to Postgres ({raw_url.split('@')[1]})")
    except Exception as exc:
        print(f"✗ Could not connect to Postgres: {exc}")
        sys.exit(1)

    rows = await conn.fetch("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'trading'
        ORDER BY table_name;
    """)
    found = {row["table_name"] for row in rows}

    all_ok = True
    for table in EXPECTED_TABLES:
        if table in found:
            print(f"✓ trading.{table} exists")
        else:
            print(
                f"✗ trading.{table} MISSING — "
                f"did you run 'alembic -c src/db/migrations/alembic.ini upgrade head'?"
            )
            all_ok = False

    await conn.close()

    if all_ok:
        print("\nAll checks passed — infrastructure ready.")
    else:
        print(
            "\nSome tables are missing. "
            "Run: alembic -c src/db/migrations/alembic.ini upgrade head"
        )
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
