# Betfair Lay-the-Draw Trading Bot — Full Specification

> **Purpose:** Pass this document to DeepSeek (generation) and Claude (review) as the authoritative project specification.  
> **Strategy:** Lay the Draw (LTD) on football markets using Betfair's Streaming API.  
> **Developer workflow:** DeepSeek generates code → Claude reviews for architecture, security, and consistency.

---

## 1. Project Overview

A fully automated trading bot that lays the draw market on football matches before kick-off, detects goals via live Betfair price movement, then greens up for a profit. The bot runs through clearly defined phases: backtest → paper trade → live (minimum stakes) → scale.

### Core trading logic
- **Entry:** Lay the draw pre-match when draw odds are ≤ 3.5
- **Exit (profit):** Back the draw after a goal is detected (odds spike > 30% in a single tick)
- **Exit (stop-loss):** Back the draw at minute 60 if no goal has been scored
- **Kill switch:** Hard circuit breaker that halts all trading if daily P&L loss exceeds a configurable threshold

---

## 2. Technology Stack

| Layer | Technology | Notes |
|---|---|---|
| Language | Python 3.11+ | Type hints required throughout |
| Betfair SDK | `betfairlightweight` | Official SDK, free |
| Bot framework | `flumine` | Wraps betfairlightweight; single class per strategy; backtest/paper/live mode via flag |
| Database | PostgreSQL 15+ | Self-hosted; all tick, order, and trade data |
| Score feed | Betfair Streaming API | Price-implied goal detection (primary); optional API-Football as secondary cross-reference |
| Dashboard | Grafana + Postgres datasource | Live P&L, market depth, alerts |
| VPS | Hetzner CX21 or DigitalOcean Droplet (£5–10/month) | Always-on; do not run on local machine |
| Config | Environment variables + YAML config file | No secrets in code |

---

## 3. Database Schema

All tables live in a single `trading` schema in Postgres.

### 3.1 `runs`
Represents one bot session (backtest, paper, or live).

| Column | Type | Description |
|---|---|---|
| `id` | UUID (PK) | |
| `mode` | VARCHAR | `backtest`, `paper`, or `live` |
| `strategy_name` | VARCHAR | e.g. `ltd_v1` |
| `started_at` | TIMESTAMPTZ | |
| `ended_at` | TIMESTAMPTZ | Null if still running |
| `total_pnl` | NUMERIC(10,4) | Net of commission |
| `commission_paid` | NUMERIC(10,4) | |

### 3.2 `markets`
One row per Betfair market processed in a run.

| Column | Type | Description |
|---|---|---|
| `id` | UUID (PK) | |
| `run_id` | UUID (FK → runs) | |
| `betfair_market_id` | VARCHAR | e.g. `1.234567890` |
| `event_name` | VARCHAR | e.g. `Arsenal v Chelsea` |
| `market_type` | VARCHAR | e.g. `MATCH_ODDS` |
| `kick_off` | TIMESTAMPTZ | |
| `status` | VARCHAR | `pending`, `active`, `settled`, `skipped` |

### 3.3 `ticks`
Price snapshots at every streaming update for the draw runner.

| Column | Type | Description |
|---|---|---|
| `id` | UUID (PK) | |
| `market_id` | UUID (FK → markets) | |
| `draw_lay_price` | NUMERIC(6,2) | Best available lay |
| `draw_back_price` | NUMERIC(6,2) | Best available back |
| `volume_matched` | BIGINT | Total matched on the market |
| `recorded_at` | TIMESTAMPTZ | |

### 3.4 `orders`
Every order placed (or simulated in paper/backtest mode).

| Column | Type | Description |
|---|---|---|
| `id` | UUID (PK) | |
| `market_id` | UUID (FK → markets) | |
| `side` | VARCHAR | `LAY` or `BACK` |
| `price` | NUMERIC(6,2) | |
| `size` | NUMERIC(10,4) | Stake in £ |
| `status` | VARCHAR | `pending`, `matched`, `lapsed`, `cancelled` |
| `betfair_bet_id` | VARCHAR | Null in paper/backtest |
| `placed_at` | TIMESTAMPTZ | |
| `matched_at` | TIMESTAMPTZ | |

### 3.5 `trades`
Completed round-trips (entry + exit pair).

| Column | Type | Description |
|---|---|---|
| `id` | UUID (PK) | |
| `market_id` | UUID (FK → markets) | |
| `entry_price` | NUMERIC(6,2) | Lay price at entry |
| `exit_price` | NUMERIC(6,2) | Back price at green-up |
| `stake` | NUMERIC(10,4) | Lay stake |
| `gross_pnl` | NUMERIC(10,4) | Before commission |
| `commission` | NUMERIC(10,4) | Betfair commission (default 5%) |
| `net_pnl` | NUMERIC(10,4) | gross_pnl − commission |
| `exit_reason` | VARCHAR | `goal_detected`, `stop_loss_time`, `kill_switch`, `manual` |
| `opened_at` | TIMESTAMPTZ | |
| `closed_at` | TIMESTAMPTZ | |

---

## 4. Project Structure

```
betfair-ltd-bot/
├── config/
│   ├── settings.yaml          # Strategy params, commission rate, kill switch thresholds
│   └── .env.example           # API keys, DB credentials (never commit real .env)
├── src/
│   ├── auth/
│   │   └── betfair_auth.py    # SSL cert login, session token management
│   ├── streaming/
│   │   └── market_stream.py   # betfairlightweight streaming connection
│   ├── strategy/
│   │   └── ltd_strategy.py    # flumine strategy class (LTD logic)
│   ├── risk/
│   │   ├── risk_manager.py    # Position sizing, liability calc, kill switch
│   │   └── stop_loss.py       # Time-based and P&L-based stop logic
│   ├── goal_detection/
│   │   └── detector.py        # Price-spike goal detection; optional API-Football cross-ref
│   ├── db/
│   │   ├── models.py          # SQLAlchemy ORM models (matching schema above)
│   │   ├── repository.py      # Repository pattern — all DB access goes here
│   │   └── migrations/        # Alembic migration files
│   ├── dashboard/
│   │   └── api.py             # FastAPI or Flask; serves live data to Grafana / WebSocket
│   └── main.py                # Entry point; reads mode flag (backtest/paper/live)
├── tests/
│   ├── unit/
│   └── integration/
├── scripts/
│   └── backtest_runner.py     # Loads historical Betfair data, runs strategy
├── grafana/
│   └── dashboards/            # Exported Grafana JSON panels
├── CLAUDE.md                  # Architecture rules for AI assistants (see Section 8)
└── requirements.txt
```

---

## 5. Strategy Implementation (`ltd_strategy.py`)

The strategy is a single `flumine` strategy class. All parameters are injected from config — no hardcoded values.

### Parameters (configurable via `settings.yaml`)
| Parameter | Default | Description |
|---|---|---|
| `max_entry_odds` | 3.5 | Won't lay draw above this price |
| `stake` | £10.00 | Lay stake per trade |
| `commission_rate` | 0.05 | 5% Betfair standard |
| `goal_spike_threshold` | 0.30 | 30% price jump triggers goal detection |
| `stop_loss_minute` | 60 | Exit if no goal by this match minute |
| `min_market_volume` | £50,000 | Skip markets below this pre-kick-off volume |
| `daily_loss_limit` | £50.00 | Kill switch threshold |

### Entry conditions (all must be true)
1. Draw lay price ≤ `max_entry_odds`
2. Pre-kick-off market volume ≥ `min_market_volume`
3. No position currently open on this market
4. Daily P&L has not breached `daily_loss_limit`

### Goal detection logic
Primary: draw lay price jumps ≥ `goal_spike_threshold` in a single streaming tick.  
Secondary (optional): cross-reference with API-Football score endpoint (polled at 5s intervals as confirmation only — never as sole trigger due to latency).

### Exit logic (priority order)
1. Goal detected → back the draw immediately at best available price
2. Match minute ≥ `stop_loss_minute` with position open → back the draw
3. Kill switch triggered (daily loss limit breached) → back all open positions, halt

---

## 6. Risk Management

### Liability calculation
```
liability = lay_stake × (lay_odds − 1)
```
This must be calculated and logged before every order. Never place an order without computing and storing the liability.

### Kill switch
- Tracks cumulative `net_pnl` for the current calendar day across all markets
- If `net_pnl < −daily_loss_limit`, set `KILL_SWITCH_ACTIVE = True`
- When active: cancel all pending orders, back any open lay positions at market price, write a `kill_switch` exit reason to `trades`, halt the main loop
- Kill switch resets on next calendar day (midnight UTC) or manual restart

### Position sizing
- Fixed stake per trade (not Kelly or variable)
- Maximum one open position per market at any time
- Maximum configurable number of simultaneous open markets (default: 3)

---

## 7. Build Phases

### Phase 1 — Betfair connection + data logger (~2 days)
**Goal:** Prove infrastructure works. Nothing else.
- Betfair API auth with SSL cert
- Streaming API connected to MATCH_ODDS markets
- Raw draw price + volume writing to `ticks` table every update
- Verify data is flowing correctly before proceeding

### Phase 2 — Backtest engine (~1 week)
**Goal:** Validate strategy edge before any live orders.
- Purchase one full Premier League season of Betfair historical tick data (approx. £50–100)
- Run `ltd_strategy.py` in `flumine` backtest mode
- Simulate realistic commission (5%) and slippage (assume 0.02 worse than best price)
- Output P&L report, win rate, average profit/loss per trade, max drawdown
- **Gate:** Only proceed to Phase 3 if backtest shows positive expectancy after commission

### Phase 3 — Paper trading (2–4 weeks)
**Goal:** Validate execution layer with live prices, fake orders.
- Run `flumine` in paper mode against real streaming data
- Compare weekly P&L to backtest expectations
- Watch for divergence (divergence = bug in fill simulation)
- Confirm stop-losses fire correctly, kill switch activates at threshold

### Phase 4 — Live minimum stakes (2–3 weeks)
**Goal:** Prove order execution works correctly with real money, not to make profit.
- Go live at £2 stake per trade
- Verify orders match, liability is calculated correctly, Betfair bet IDs are stored
- Confirm commission is deducted correctly in `trades` table

### Phase 5 — Dashboard (after Phase 4 has real data)
**Goal:** Build monitoring on top of real data.
- Grafana connected to Postgres
- Panels: daily P&L, win rate, active markets, draw price over time, alert feed
- WebSocket endpoint for live order book depth (for the draw runner)
- Alert triggers: price spike > 30%, spread widening, volume below threshold at kick-off

### Phase 6 — Scale + iterate
- Increase stakes gradually (£2 → £5 → £10)
- Add second strategy (e.g. Over 2.5 Goals)
- Continuous backtest loop running on growing live dataset

---

## 8. CLAUDE.md (Paste into repo root)

This file is read by both DeepSeek and Claude during every coding session.

```markdown
# Architecture rules — Betfair LTD Bot

## Structure
- All Betfair API calls go through `src/streaming/` and `src/auth/` — never inline
- All database access goes through `src/db/repository.py` — no raw SQL elsewhere
- Strategy logic lives only in `src/strategy/ltd_strategy.py`
- Risk checks live only in `src/risk/risk_manager.py`
- Config values come from `settings.yaml` or env vars — no hardcoded numbers in strategy code

## Naming
- Files: `snake_case.py`
- Classes: `PascalCase`
- Functions and variables: `snake_case`
- Constants: `SCREAMING_SNAKE_CASE`

## Code style
- Python 3.11+, type hints on all function signatures
- No `Any` types without a comment explaining why
- Async/await for all I/O — no blocking calls in the event loop
- All public functions get a docstring
- Max function length: 40 lines — extract helpers if longer

## Testing
- Unit tests required for strategy logic and risk manager
- Integration tests for DB writes and Betfair API interactions
- Use pytest
- Target 80%+ coverage on new files

## Security
- Never log API keys, session tokens, or Betfair credentials
- Kill switch state must be checked before every order placement
- Liability must be calculated and logged before every order

## Session notes
<!-- Update before switching from DeepSeek to Claude review -->
<!-- Date: YYYY-MM-DD -->
<!-- Task: what was built -->
<!-- Files changed: list them -->
<!-- Open questions for Claude review: -->
```

---

## 9. Developer Workflow (DeepSeek → Claude)

### DeepSeek session (code generation)
```bash
export ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
export ANTHROPIC_AUTH_TOKEN=<deepseek-key>
export ANTHROPIC_MODEL=deepseek-v4-pro[1m]
claude
```

### Claude review session
```bash
unset ANTHROPIC_BASE_URL
export ANTHROPIC_AUTH_TOKEN=<anthropic-key>
unset ANTHROPIC_MODEL
claude "Review the latest git diff for architectural alignment, security, and consistency with CLAUDE.md. Flag anything that should change and explain why."
```

### Handoff checklist (before switching to Claude)
- [ ] DeepSeek has committed all changes
- [ ] `CLAUDE.md` session notes section updated with what was built and open questions
- [ ] Tests pass locally
- [ ] No secrets or hardcoded values introduced

---

## 10. External Dependencies & Cost

| Dependency | Cost | Notes |
|---|---|---|
| `betfairlightweight` | Free | pip install |
| `flumine` | Free | pip install |
| PostgreSQL | Free | Self-hosted on VPS |
| Grafana | Free | Self-hosted on VPS |
| Betfair API key | Free | Apply via developer portal; funded account required |
| Historical tick data | £50–100 one-off | One Premier League season; purchase from Betfair |
| API-Football | Free tier / £10/month | 100 req/day free; paid if higher frequency needed |
| VPS (Hetzner/DigitalOcean) | £5–10/month | For always-on bot and DB |
| **Total running cost** | **~£15–30/month** | Excluding historical data purchase |

---

## 11. Explicitly Out of Scope (for v1)

- No web UI (Grafana only)
- No horse racing or other sports
- No multi-leg or exotic bets
- No ML-based prediction (pure rules-based strategy)
- No mobile app
- No user accounts or multi-user support
- No automated staking growth (Kelly criterion deferred to v2)
