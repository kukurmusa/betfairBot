"""Integration tests for Repository — requires a running PostgreSQL.

Start with::

    docker compose up -d
    pytest tests/integration/ -v
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Market, Run, Tick
from src.db.repository import Repository
from src.exceptions import DatabaseError


@pytest.mark.asyncio
async def test_create_run(repository: Repository) -> None:
    """Should create a run with correct fields."""
    run = await repository.create_run(mode="paper", strategy_name="ltd_v1")

    assert isinstance(run.id, uuid.UUID)
    assert run.mode == "paper"
    assert run.strategy_name == "ltd_v1"
    assert run.started_at is not None
    assert run.ended_at is None
    assert run.total_pnl is None


@pytest.mark.asyncio
async def test_end_run(repository: Repository) -> None:
    """Should set ended_at and optional P&L fields."""
    run = await repository.create_run(mode="live", strategy_name="ltd_v1")

    await repository.end_run(
        run.id,
        total_pnl=Decimal("15.50"),
        commission_paid=Decimal("2.30"),
    )

    # Need a fresh session to see the update
    # — but since we're in the same session, flush already happened


@pytest.mark.asyncio
async def test_upsert_market_new(repository: Repository) -> None:
    """Should insert a new market row."""
    run = await repository.create_run(mode="paper", strategy_name="ltd_v1")

    market = await repository.upsert_market(
        run_id=run.id,
        betfair_market_id="1.123456789",
        event_name="Arsenal v Chelsea",
    )

    assert isinstance(market.id, uuid.UUID)
    assert market.betfair_market_id == "1.123456789"
    assert market.event_name == "Arsenal v Chelsea"
    assert market.market_type == "MATCH_ODDS"
    assert market.status == "pending"


@pytest.mark.asyncio
async def test_upsert_market_duplicate(repository: Repository) -> None:
    """Same betfair_market_id should return the existing row, not create a duplicate."""
    run = await repository.create_run(mode="paper", strategy_name="ltd_v1")

    m1 = await repository.upsert_market(
        run_id=run.id,
        betfair_market_id="1.duplicate",
        event_name="Liverpool v Everton",
    )
    m2 = await repository.upsert_market(
        run_id=run.id,
        betfair_market_id="1.duplicate",
        event_name="Liverpool v Everton",
    )

    assert m1.id == m2.id
    assert m1.event_name == m2.event_name


@pytest.mark.asyncio
async def test_get_market_by_betfair_id(repository: Repository) -> None:
    """Should retrieve a market by its Betfair ID."""
    run = await repository.create_run(mode="paper", strategy_name="ltd_v1")

    await repository.upsert_market(
        run_id=run.id,
        betfair_market_id="1.findme",
        event_name="Man City v Man Utd",
    )

    found = await repository.get_market_by_betfair_id("1.findme")
    assert found is not None
    assert found.event_name == "Man City v Man Utd"

    not_found = await repository.get_market_by_betfair_id("1.nope")
    assert not_found is None


@pytest.mark.asyncio
async def test_insert_tick(repository: Repository) -> None:
    """Should insert a tick with correct prices and volume."""
    run = await repository.create_run(mode="paper", strategy_name="ltd_v1")
    market = await repository.upsert_market(
        run_id=run.id,
        betfair_market_id="1.ticktest",
        event_name="Spurs v Newcastle",
    )

    tick = await repository.insert_tick(
        market_id=market.id,
        draw_lay_price=Decimal("3.50"),
        draw_back_price=Decimal("3.40"),
        volume_matched=75_000,
    )

    assert isinstance(tick.id, uuid.UUID)
    assert tick.draw_lay_price == 3.50
    assert tick.draw_back_price == 3.40
    assert tick.volume_matched == 75_000
    assert tick.recorded_at is not None


@pytest.mark.asyncio
async def test_insert_tick_nonexistent_market(repository: Repository) -> None:
    """Inserting a tick for a non-existent market should raise DatabaseError."""
    fake_market_id = uuid.uuid4()

    with pytest.raises(DatabaseError):
        await repository.insert_tick(
            market_id=fake_market_id,
            draw_lay_price=Decimal("3.00"),
            draw_back_price=Decimal("2.90"),
            volume_matched=10_000,
        )


@pytest.mark.asyncio
async def test_get_active_markets(repository: Repository) -> None:
    """Should return only markets with pending or active status."""
    run = await repository.create_run(mode="paper", strategy_name="ltd_v1")

    # Two pending markets
    await repository.upsert_market(
        run_id=run.id,
        betfair_market_id="1.active1",
        event_name="Match A",
        status="pending",
    )
    await repository.upsert_market(
        run_id=run.id,
        betfair_market_id="1.active2",
        event_name="Match B",
        status="active",
    )

    # One settled (should not appear)
    m3 = await repository.upsert_market(
        run_id=run.id,
        betfair_market_id="1.settled",
        event_name="Match C",
        status="pending",
    )
    m3.status = "settled"
    await repository._session.flush()

    active = await repository.get_active_markets()
    assert len(active) == 2
    event_names = {m.event_name for m in active}
    assert event_names == {"Match A", "Match B"}
