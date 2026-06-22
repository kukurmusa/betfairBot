# Betfair LTD Trading Bot — Phase Milestones & Features

> Pass this alongside `betfair-ltd-bot-spec.md` to DeepSeek/Claude.  
> Each phase has a clear gate — do not proceed to the next phase until all gates are green.

---

## Phase 1 — Betfair Connection & Data Logger

**Goal:** Prove the connection works and raw data is flowing into Postgres. No strategy logic yet.

### Features
- Betfair API authentication (username/password/app key via `.env`)
- Streaming API connection to `MATCH_ODDS` markets
- Subscribe to football markets only (filter by event type ID `1`)
- Parse `RunnerChange` messages and extract draw runner price (selection ID for the draw)
- Write raw draw price ticks to `ticks` table in Postgres with timestamp
- Heartbeat logging — confirm connection is alive every 60 seconds
- Graceful reconnect on stream disconnect (exponential backoff, max 5 retries)
- Basic CLI output: market name, current draw odds, tick count

### Gate before Phase 2
- [ ] Bot connects and stays connected for 90+ minutes without intervention
- [ ] Tick data visible in Postgres via `psql` or pgAdmin
- [ ] No memory leaks observed over a full evening session
- [ ] Reconnect logic tested by manually killing the stream

---

## Phase 2 — Backtester

**Goal:** Validate the LTD strategy against historical data before risking any money.

### Features
- Load historical tick data from Betfair (purchased `.bz2` files) into Postgres
- Replay engine: iterate through ticks in time order, simulate strategy decisions
- Implement full strategy logic in replay mode:
  - Entry: lay draw when pre-match odds ≤ 3.5
  - Goal detection: odds spike > 30% in a single tick → assume goal scored
  - Exit (profit): back draw after goal detected
  - Exit (stop-loss): back draw at match minute 60 if no goal
- P&L calculation per trade: account for Betfair 5% commission on winnings
- Output summary report per backtest run:
  - Total trades, win rate, avg profit/loss per trade
  - Max drawdown, Sharpe ratio (basic), ROI %
- Save all backtest trades to `trades` table with `run_id` tag
- CLI flag to run single market or batch (entire dataset)

### Gate before Phase 3
- [ ] Strategy logic produces consistent, reproducible results across multiple runs
- [ ] P&L calculations manually verified against at least 10 sample trades
- [ ] Strategy shows positive expectation over 200+ historical markets
- [ ] Backtest report exports correctly to CSV

---

## Phase 3 — Paper Trading (Live Prices, Fake Orders)

**Goal:** Run the strategy against live Betfair prices in real-time, but place no actual bets.

### Features
- All Phase 1 streaming infrastructure reused
- Strategy engine runs in real-time against live tick feed
- Simulated order placement: log what would have been bet, at what price and stake
- Simulated P&L tracking: update running balance as if bets were placed
- `paper_mode = True` flag in config — single toggle, no code changes needed to go live
- Orders written to `orders` table with `mode = paper`
- Kill switch logic active even in paper mode (test the circuit breaker)
- Console output: every entry/exit decision logged with reasoning

### Gate before Phase 4
- [ ] Paper trading runs unattended for 7+ consecutive days
- [ ] Paper P&L is directionally consistent with backtest results
- [ ] No crashes or silent failures observed
- [ ] Kill switch triggers correctly when simulated loss threshold is hit

---

## Phase 4 — Live Trading (Minimum Stakes)

**Goal:** Place real bets at minimum stake (£2 lay liability) to validate execution under real conditions.

### Features
- Switch `paper_mode = False` in config
- Betfair order placement via `flumine`:
  - `LimitOrder` for lay entry and back exit
  - Order size validation before placement (min £2 liability enforced)
  - Order status polling until matched or cancelled
- Hard kill switch: if daily P&L loss > configurable threshold → halt all trading, alert
- Max open positions: no more than 3 concurrent active lay bets
- Liability cap: total unhedged liability never exceeds configurable limit
- All placed orders logged to `orders` table with Betfair bet ID
- All completed round-trips logged to `trades` table with actual P&L
- Email/Telegram alert on: kill switch trigger, connection failure, unexpected exception
- VPS deployment: Docker Compose with `restart: always`

### Gate before Phase 5
- [ ] 50+ live trades completed without manual intervention
- [ ] Live P&L directionally matches paper trading results
- [ ] Kill switch tested in a controlled way (reduced threshold, verify halt)
- [ ] Bot survives VPS reboot automatically

---

## Phase 5 — Monitoring Dashboard (Grafana)

**Goal:** Visibility into bot performance without needing to SSH into the server.

### Features
- Grafana connected to Postgres via `postgresql` datasource
- Panels:
  - Running P&L over time (line chart)
  - Win rate % (stat panel)
  - Number of trades today / this week / all time
  - Active open positions (table)
  - Draw odds at entry vs exit (scatter plot)
  - Kill switch status (green/red indicator)
  - Last heartbeat timestamp
  - Recent trade log (table, last 20 rows)
- Dashboard auto-refreshes every 30 seconds
- Grafana alerting: notify on kill switch trigger and no-heartbeat for > 5 mins

### Gate before Phase 6
- [ ] All panels populated with real data from Phase 4 trades
- [ ] Alerts confirmed working via test trigger
- [ ] Dashboard accessible remotely (Grafana behind basic auth or Cloudflare tunnel)

---

## Phase 6 — Scale & Optimise

**Goal:** Increase stake size and refine the strategy based on live data.

### Features
- Stake sizing: configurable per-trade stake, increase in increments once 200+ live trades logged
- Strategy parameter tuning: adjust entry threshold (3.5) and goal detection sensitivity (30%) based on live data
- Market selection filters: add minimum liquidity filter, exclude low-volume markets
- Multi-market concurrency: safely handle up to 10 concurrent markets (flumine supports this natively)
- Expanded logging: log market liquidity at entry, number of runners, league/competition
- A/B config testing: run two parameter sets simultaneously on different markets, compare results
- Weekly P&L report auto-generated and emailed every Monday 08:00

### Gate (ongoing)
- [ ] 500+ live trades with positive expectation confirmed
- [ ] Stake increase approved only after reviewing rolling 30-day P&L
- [ ] No single market accounts for > 20% of total volume

---

## Summary Table

| Phase | Name | Key Deliverable | Risk Level |
|---|---|---|---|
| 1 | Connection & Logger | Data in Postgres | Zero — no orders |
| 2 | Backtester | Historical P&L validated | Zero — no orders |
| 3 | Paper Trading | Live sim running 7 days | Zero — no real money |
| 4 | Live (min stakes) | Real bets, £2 liability | Low — capped exposure |
| 5 | Dashboard | Grafana visibility | Zero — monitoring only |
| 6 | Scale | Higher stakes, optimised | Medium — managed increase |

---

## Config Flags Reference

| Flag | Default | Description |
|---|---|---|
| `paper_mode` | `True` | Set `False` to place real bets |
| `max_draw_odds` | `3.5` | Maximum draw odds to enter |
| `goal_spike_threshold` | `0.30` | % odds increase to trigger goal detection |
| `stop_loss_minute` | `60` | Minute to exit if no goal |
| `max_open_positions` | `3` | Concurrent lay bets cap |
| `daily_loss_limit` | `10.00` | £ loss to trigger kill switch |
| `max_liability_per_bet` | `5.00` | £ max unhedged liability per bet |
| `stake_size` | `2.00` | £ lay stake per trade |
