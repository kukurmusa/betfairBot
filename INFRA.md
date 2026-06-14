# Betfair LTD Bot — Infrastructure Setup (INFRA.md)

> **How to use this file:** Pass this entire file to DeepSeek/Claude to set up the infrastructure layer.
> This is a one-time setup task. Complete this before any Phase 1 bot code is written.
> All services run in Docker. The bot Python process runs on the host (not in Docker).

**Schema approach:** Alembic is the single source of truth for all schema creation and changes.
There is no `init.sql`. Alembic creates all tables on first run via `alembic upgrade head`.
The bot runtime uses `asyncpg`; Alembic uses `psycopg2` for migrations — no asyncpg in Alembic.

---

## 1. Directory Structure (Infrastructure Files)

```
betfair-ltd-bot/
├── docker-compose.yml              # Postgres + Grafana (at repo root)
├── alembic.ini                     # Alembic config at repo root
├── .env.example                    # Template — copy to .env, never commit .env
├── .env                            # gitignored — real credentials live here
├── src/
│   └── db/
│       ├── models.py               # SQLAlchemy async models — Alembic reads Base.metadata
│       ├── repository.py           # All DB access goes through here
│       └── migrations/
│           ├── env.py              # Alembic environment (reads DATABASE_URL_SYNC)
│           └── versions/           # Migration files
│               ├── 0001_initial_schema.py
│               └── 0002_orders_trades.py
└── scripts/
    └── db_check.py                 # Async sanity check — verifies all tables exist
```

---

## 2. Environment Variables

### `.env.example`
Copy this to `.env` and fill in real values. The `.env` file must be in `.gitignore`.

```env
# Betfair API
BETFAIR_APP_KEY=your_app_key_here
BETFAIR_USERNAME=your_betfair_username
BETFAIR_PASSWORD=your_betfair_password
BETFAIR_CERT_PATH=/path/to/client-2048.crt
BETFAIR_CERT_KEY_PATH=/path/to/client-2048.key

# PostgreSQL (used by Docker Compose AND the Python bot)
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=betfair_ltd
POSTGRES_USER=bot
POSTGRES_PASSWORD=bot_password

# Async connection string for SQLAlchemy + bot runtime (asyncpg driver)
DATABASE_URL=postgresql+asyncpg://bot:bot_password@localhost:5432/betfair_ltd

# Sync connection string for Alembic migrations only (psycopg2 driver)
DATABASE_URL_SYNC=postgresql+psycopg2://bot:bot_password@localhost:5432/betfair_ltd

# API-Football (optional score confirmation feed)
# API_FOOTBALL_KEY=your_api_football_key

# Dashboard API (Phase 5)
# DASHBOARD_HOST=0.0.0.0
# DASHBOARD_PORT=8000

# Grafana (Phase 5)
# GRAFANA_ADMIN_USER=admin
# GRAFANA_ADMIN_PASSWORD=change_me_grafana_password
```

> **Why two DATABASE_URL vars?** The bot uses `asyncpg` for all async DB operations.
> Alembic requires a synchronous driver to run migrations — it uses `psycopg2` only for
> that purpose. The bot code never imports psycopg2 directly.

### `.gitignore` additions
```
.env
*.crt
*.key
*.pem
logs/
__pycache__/
*.pyc
.pytest_cache/
```

---

## 3. Docker Compose

### `docker-compose.yml`

No `init.sql` mount — Alembic handles all schema creation. Uses `${}` env-var
interpolation so credentials are never hardcoded.

```yaml
services:
  postgres:
    image: postgres:15-alpine
    container_name: betfair_postgres
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-betfair_ltd}
      POSTGRES_USER: ${POSTGRES_USER:-bot}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-bot_password}
    ports:
      - "${POSTGRES_PORT:-5432}:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test:
        - CMD-SHELL
        - pg_isready -U ${POSTGRES_USER:-bot} -d ${POSTGRES_DB:-betfair_ltd}
      interval: 10s
      timeout: 5s
      retries: 5

  grafana:
    image: grafana/grafana:11.6.0
    container_name: betfair_grafana
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      GF_SECURITY_ADMIN_USER: ${GRAFANA_ADMIN_USER:-admin}
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:-admin}
      GF_INSTALL_PLUGINS: grafana-clock-panel
    ports:
      - "3000:3000"
    volumes:
      - grafana_data:/var/lib/grafana

volumes:
  postgres_data:
  grafana_data:
```

**Commands:**
```bash
# Start both services (run from repo root)
docker compose --env-file .env up -d

# Stop
docker compose down

# Stop and wipe all data (destructive — resets schema too)
docker compose down -v

# View logs
docker compose logs -f postgres
docker compose logs -f grafana

# Check health
docker compose ps
```

---

## 4. Grafana Provisioning

Grafana provisioning (datasources, dashboards) is set up in **Phase 5** after live
trading data exists. Until then, Grafana starts with default credentials from
`.env` / `docker-compose.yml` and the Postgres datasource can be configured
manually in the UI.

**Accessing Grafana:**
- URL: `http://localhost:3000`
- Login: credentials from `.env` (`GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD`)

---

## 5. Alembic (Single Source of Schema Truth)

Alembic creates the initial schema AND manages all future changes.
The config file lives at repo root (`alembic.ini`); migrations live at `src/db/migrations/`.

### Installation
```bash
pip install alembic asyncpg psycopg2-binary sqlalchemy[asyncio] python-dotenv
```

> `psycopg2-binary` is installed for Alembic's sync runner only.
> The bot itself only uses `asyncpg` — never import psycopg2 in bot code.

### `alembic.ini`

```ini
[alembic]
script_location = src/db/migrations
prepend_sys_path = .
file_template = %%(year)d%%(month).2d%%(day).2d_%%(rev)s_%%(slug)s
sqlalchemy.url = postgresql+psycopg2://bot:bot_password@localhost:5432/betfair_ltd
```

> The `sqlalchemy.url` in `alembic.ini` is a fallback for offline mode only.
> `env.py` overrides it with `DATABASE_URL_SYNC` from `.env` at runtime.

### `src/db/migrations/env.py`

Uses `DATABASE_URL_SYNC` (psycopg2) from `.env`. Imports `Base.metadata` from
`src.db.models` so `--autogenerate` works correctly.

```python
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool
from dotenv import load_dotenv

# Ensure repo root is on sys.path
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
```

### Alembic commands
All commands run from the **repo root**.

```bash
# First-time setup: apply all existing migrations to create the full schema
alembic upgrade head

# After modifying models.py: generate and apply a new migration
alembic revision --autogenerate -m "describe_change_here"
alembic upgrade head

# Roll back one migration
alembic downgrade -1

# Show current applied migration
alembic current

# Show full migration history
alembic history
```

---

## 6. DB Sanity Check Script

### `scripts/db_check.py`

Uses `asyncpg` directly (same driver as the bot) — no psycopg2.
Run after `docker compose up` + `alembic upgrade head` to confirm everything is ready.

```python
"""Async sanity check — verifies Postgres is up and all tables exist."""
import asyncio
import os
import sys
import asyncpg
from dotenv import load_dotenv

load_dotenv()

EXPECTED_TABLES = ["runs", "markets", "ticks", "orders", "trades"]


async def main() -> None:
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
            print(f"✗ trading.{table} MISSING — "
                  f"did you run 'alembic upgrade head'?")
            all_ok = False

    await conn.close()

    if all_ok:
        print("\nAll checks passed — infrastructure ready.")
    else:
        print("\nSome tables are missing. Run: alembic upgrade head")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
```

```bash
python scripts/db_check.py
```

---

## 7. VPS Deployment (Hetzner / DigitalOcean)

### Recommended spec
- **Provider:** Hetzner CX21 or DigitalOcean Basic Droplet
- **OS:** Ubuntu 24.04 LTS
- **RAM:** 2GB minimum (Postgres + Grafana + bot fits comfortably)
- **Storage:** 20GB SSD (tick data grows — monitor monthly)
- **Cost:** £5–10/month

### First-time server setup
```bash
# SSH in as root, then:
apt update && apt upgrade -y

# Create a non-root user
adduser botuser
usermod -aG sudo botuser
su - botuser

# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker botuser

# Install Python 3.11
sudo apt install -y python3.11 python3.11-venv python3-pip git

# Clone your repo
git clone https://github.com/yourname/betfair-ltd-bot.git
cd betfair-ltd-bot

# Set up Python venv
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Copy and fill in .env
cp .env.example .env
nano .env

# Start Docker services
docker compose --env-file .env up -d

# Wait for Postgres to be healthy, then create schema
sleep 15
alembic upgrade head

# Verify
python scripts/db_check.py
```

### Running the bot as a systemd service

Create `/etc/systemd/system/betfair-bot.service`:

```ini
[Unit]
Description=Betfair LTD Trading Bot
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=botuser
WorkingDirectory=/home/botuser/betfair-ltd-bot
EnvironmentFile=/home/botuser/betfair-ltd-bot/.env
ExecStart=/home/botuser/betfair-ltd-bot/venv/bin/python -m src.main
Restart=on-failure
RestartSec=30
StandardOutput=append:/home/botuser/betfair-ltd-bot/logs/bot.log
StandardError=append:/home/botuser/betfair-ltd-bot/logs/bot_error.log

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable betfair-bot
sudo systemctl start betfair-bot

# Check status
sudo systemctl status betfair-bot

# View live logs
tail -f logs/bot.log
```

### Firewall rules
```bash
sudo ufw allow ssh
sudo ufw enable

# Restrict Grafana and dashboard API to your IP only
sudo ufw allow from YOUR.IP.ADDRESS to any port 3000
sudo ufw allow from YOUR.IP.ADDRESS to any port 8000
```

### Backups
```bash
# Add to crontab (crontab -e) — daily backup at 3am
0 3 * * * docker exec betfair_postgres pg_dump -U bot betfair_ltd | gzip > /home/botuser/backups/db_$(date +\%Y\%m\%d).sql.gz

# Keep only last 30 days
0 4 * * * find /home/botuser/backups -name "*.sql.gz" -mtime +30 -delete
```

---

## 8. Setup Order (Do This Exactly)

```
1.  Clone repo, copy .env.example → .env, fill in all values
2.  Confirm .env and *.crt / *.key are in .gitignore
3.  docker compose --env-file .env up -d
4.  Wait ~15 seconds for Postgres healthcheck to pass
5.  docker compose ps   ← postgres should show "healthy"
6.  alembic upgrade head   ← creates all tables (runs, markets, ticks, orders, trades)
7.  python scripts/db_check.py   ← must show all green before continuing
8.  Open http://localhost:3000 — verify Grafana loads
9.  Proceed to Phase 1 bot code
```

---

## 9. Common Issues

| Symptom | Likely cause | Fix |
|---|---|---|
| `db_check.py` — connection refused | Postgres not healthy yet | Wait 30s, check `docker compose ps`, retry |
| Tables missing after `alembic upgrade head` | `env.py` can't import `src.db.models` | Run from repo root; check `sys.path` insert in `env.py` |
| Alembic `Can't locate revision` | `versions/` directory empty | Run `alembic revision --autogenerate -m "init"` first |
| Grafana connects but shows no data | Grafana datasource not configured | Configure Postgres datasource in Grafana UI (Phase 5 automates this) |
| `asyncpg` connection error in `db_check.py` | URL still has `+asyncpg` prefix | The script strips it automatically — check `DATABASE_URL` in `.env` |
| Alembic `target database is not up to date` on re-run | Previous migration partially applied | Run `alembic current` to see state, then `upgrade head` again |
| `psycopg2` import error during `alembic upgrade head` | `psycopg2-binary` not installed | Run `pip install psycopg2-binary` |
