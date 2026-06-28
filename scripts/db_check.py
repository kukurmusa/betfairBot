"""DB sanity check — verifies Postgres is up and all tables exist.

Uses psycopg2 (same driver as the bot runtime and Alembic).
Run after ``docker compose up`` and ``alembic upgrade head``.

Usage::

    python scripts/db_check.py
"""

import os
import sys

import psycopg2
from dotenv import load_dotenv

load_dotenv()

EXPECTED_TABLES = ["runs", "markets", "ticks", "orders", "trades"]


def main() -> None:
    """Connect to Postgres and verify all expected tables exist."""
    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg2://bot:bot_password@localhost:5432/betfair_ltd",
    )
    # psycopg2 uses plain postgresql:// — strip the SQLAlchemy driver prefix
    raw_url = database_url.split("://", 1)
    raw_url = "postgresql://" + raw_url[1] if len(raw_url) == 2 else database_url

    try:
        conn = psycopg2.connect(raw_url)
        print(f"✓ Connected to Postgres ({raw_url.split('@')[1]})")
    except Exception as exc:
        print(f"✗ Could not connect to Postgres: {exc}")
        sys.exit(1)

    cur = conn.cursor()
    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'trading'
        ORDER BY table_name;
    """)
    found = {row[0] for row in cur.fetchall()}
    cur.close()
    conn.close()

    all_ok = True
    for table in EXPECTED_TABLES:
        if table in found:
            print(f"✓ trading.{table} exists")
        else:
            print(f"✗ trading.{table} MISSING — did you run 'alembic upgrade head'?")
            all_ok = False

    if all_ok:
        print("\nAll checks passed — infrastructure ready.")
    else:
        print("\nSome tables are missing. Run: alembic upgrade head")
        sys.exit(1)


if __name__ == "__main__":
    main()
