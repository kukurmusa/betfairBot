# Architecture rules — Betfair LTD Bot

## Structure
- All Betfair API calls go through `src/streaming/` and `src/auth/` — never inline
- All database access goes through `src/db/repository.py` — no raw SQL elsewhere
- Strategy logic lives only in `src/strategy/ltd_strategy.py`
- Risk checks live only in `src/risk/risk_manager.py`
- Config values come from `settings.yaml` or env vars — no hardcoded numbers in strategy code

## Naming conventions
- Files: `snake_case.py`
- Classes: `PascalCase`
- Functions and variables: `snake_case`
- Constants: `SCREAMING_SNAKE_CASE`
- Test files: `test_*.py` in `tests/unit/` or `tests/integration/`

## Code style
- Python 3.11+, type hints on all function signatures
- No `Any` types without a comment explaining why
- Synchronous code throughout — Flumine owns the event loop; do not introduce async/await
- All public functions get a docstring
- Max function length: 40 lines — extract helpers if longer

## Testing requirements
- Unit tests required for strategy logic and risk manager
- Integration tests for DB writes and Betfair API interactions
- Use pytest
- Target 80%+ coverage on new files

## Security rules
- Never log API keys, session tokens, or Betfair credentials
- Kill switch state must be checked before every order placement
- Liability must be calculated and logged before every order
- Validate all config values at startup — fail fast on missing or invalid params

---

## Session notes
<!-- Update before switching from DeepSeek to Claude review -->
<!--
Date: 2026-06-14
Task: what was built
Files changed: list them
DeepSeek notes: design decisions, trade-offs, known limitations
Review focus: specific areas for Claude to scrutinise
-->
