#!/usr/bin/env bash
# Container startup: decode SSL certs, run migrations, start bot.
set -euo pipefail

# ------------------------------------------------------------------
# 1. SSL certificates
#    On Railway, certs arrive as base64 env vars.
#    BETFAIR_CERT_B64     → /tmp/betfair.crt  → BETFAIR_CERT_PATH
#    BETFAIR_CERT_KEY_B64 → /tmp/betfair.key  → BETFAIR_CERT_KEY_PATH
# ------------------------------------------------------------------
if [ -n "${BETFAIR_CERT_B64:-}" ]; then
    echo "$BETFAIR_CERT_B64" | base64 -d > /tmp/betfair.crt
    export BETFAIR_CERT_PATH=/tmp/betfair.crt
    echo "[start.sh] SSL cert written to /tmp/betfair.crt"
fi

if [ -n "${BETFAIR_CERT_KEY_B64:-}" ]; then
    echo "$BETFAIR_CERT_KEY_B64" | base64 -d > /tmp/betfair.key
    export BETFAIR_CERT_KEY_PATH=/tmp/betfair.key
    echo "[start.sh] SSL key written to /tmp/betfair.key"
fi

# ------------------------------------------------------------------
# 2. DATABASE_URL normalisation
#    Railway injects postgresql:// — SQLAlchemy needs postgresql+psycopg2://
# ------------------------------------------------------------------
if [ -n "${DATABASE_URL:-}" ]; then
    export DATABASE_URL="${DATABASE_URL/postgresql:\/\//postgresql+psycopg2:\/\/}"
    export DATABASE_URL_SYNC="$DATABASE_URL"
fi

# ------------------------------------------------------------------
# 3. Schema + migrations  (idempotent — safe to run on every start)
# ------------------------------------------------------------------
echo "[start.sh] Running Alembic migrations..."
alembic upgrade head
echo "[start.sh] Migrations complete."

# ------------------------------------------------------------------
# 4. Start the bot
# ------------------------------------------------------------------
echo "[start.sh] Starting bot..."
exec python -m src.main
