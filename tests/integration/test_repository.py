"""Integration tests for Repository — requires a running PostgreSQL.

Start with::

    docker compose up -d
    pytest tests/integration/ -v
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from src.db.models import Market, Run, Tick
from src.db.repository import Repository
from src.exceptions import DatabaseError


def test_create_run(repository: Repository) -> None:
    """Should create a run with correct fields."""
    run = repository.create_run(mode="paper", strategy_name="ltd_v1")

    assert isinstance(run.id, uuid.UUID)
    assert run.mode == "paper"
    assert run.strategy_name == "ltd_v1"
    assert run.started_at is not None
    assert run.ended_at is None
    assert run.total_pnl is None


def test_end_run(repository: Repository) -> None:
    """Should set ended_at and optional P&L fields."""
    run = repository.create_run(mode="live", strategy_name="ltd_v1")

    repository.end_run(
        run.id,
        total_pnl=Decimal("15.50"),
        commission_paid=Decimal("2.30"),
    )

    refreshed = repository._session.get(Run, run.id)
    assert refreshed is not None
    assert refreshed.ended_at is not None
    assert abs(refreshed.total_pnl - 15.50) < 0.01
    assert abs(refreshed.commission_paid - 2.30) < 0.01


def test_upsert_market_new(repository: Repository) -> None:
    """Should insert a new market row."""
    run = repository.create_run(mode="paper", strategy_name="ltd_v1")

    market = repository.upsert_market(
        run_id=run.id,
        betfair_market_id="1.123456789",
        event_name="Arsenal v Chelsea",
    )

    assert isinstance(market.id, uuid.UUID)
    assert market.betfair_market_id == "1.123456789"
    assert market.event_name == "Arsenal v Chelsea"
    assert market.market_type == "MATCH_ODDS"
    assert market.status == "pending"


def test_upsert_market_duplicate(repository: Repository) -> None:
    """Same betfair_market_id should return the existing row, not create a duplicate."""
    run = repository.create_run(mode="paper", strategy_name="ltd_v1")

    m1 = repository.upsert_market(
        run_id=run.id,
        betfair_market_id="1.duplicate",
        event_name="Liverpool v Everton",
    )
    m2 = repository.upsert_market(
        run_id=run.id,
        betfair_market_id="1.duplicate",
        event_name="Liverpool v Everton",
    )

    assert m1.id == m2.id
    assert m1.event_name == m2.event_name


def test_get_market_by_betfair_id(repository: Repository) -> None:
    """Should retrieve a market by its Betfair ID."""
    run = repository.create_run(mode="paper", strategy_name="ltd_v1")

    repository.upsert_market(
        run_id=run.id,
        betfair_market_id="1.findme",
        event_name="Man City v Man Utd",
    )

    found = repository.get_market_by_betfair_id("1.findme")
    assert found is not None
    assert found.event_name == "Man City v Man Utd"

    not_found = repository.get_market_by_betfair_id("1.nope")
    assert not_found is None


def test_insert_tick(repository: Repository) -> None:
    """Should insert a tick with correct prices and volume."""
    run = repository.create_run(mode="paper", strategy_name="ltd_v1")
    market = repository.upsert_market(
        run_id=run.id,
        betfair_market_id="1.ticktest",
        event_name="Spurs v Newcastle",
    )

    tick = repository.insert_tick(
        market_id=market.id,
        draw_lay_price=Decimal("3.50"),
        draw_back_price=Decimal("3.40"),
        volume_matched=75_000,
    )

    assert isinstance(tick.id, uuid.UUID)
    assert abs(tick.draw_lay_price - 3.50) < 0.001
    assert abs(tick.draw_back_price - 3.40) < 0.001
    assert tick.volume_matched == 75_000
    assert tick.recorded_at is not None


def test_insert_tick_nonexistent_market(repository: Repository) -> None:
    """Inserting a tick for a non-existent market should raise DatabaseError."""
    fake_market_id = uuid.uuid4()

    with pytest.raises(DatabaseError):
        repository.insert_tick(
            market_id=fake_market_id,
            draw_lay_price=Decimal("3.00"),
            draw_back_price=Decimal("2.90"),
            volume_matched=10_000,
        )


def test_get_active_markets(repository: Repository) -> None:
    """Should return only markets with pending or active status."""
    run = repository.create_run(mode="paper", strategy_name="ltd_v1")

    repository.upsert_market(
        run_id=run.id,
        betfair_market_id="1.active1",
        event_name="Match A",
        status="pending",
    )
    repository.upsert_market(
        run_id=run.id,
        betfair_market_id="1.active2",
        event_name="Match B",
        status="active",
    )

    m3 = repository.upsert_market(
        run_id=run.id,
        betfair_market_id="1.settled",
        event_name="Match C",
        status="pending",
    )
    m3.status = "settled"
    repository._session.flush()

    active = repository.get_active_markets()
    assert len(active) == 2
    event_names = {m.event_name for m in active}
    assert event_names == {"Match A", "Match B"}


def test_insert_order(repository: Repository) -> None:
    """Should create an order row with correct fields."""
    run = repository.create_run(mode="paper", strategy_name="ltd_v1")
    market = repository.upsert_market(
        run_id=run.id,
        betfair_market_id="1.ordertest",
        event_name="West Ham v Fulham",
    )

    order = repository.insert_order(
        market_id=market.id,
        run_id=run.id,
        side="LAY",
        price=Decimal("3.20"),
        size=Decimal("10.00"),
    )

    assert isinstance(order.id, uuid.UUID)
    assert order.side == "LAY"
    assert abs(order.price - 3.20) < 0.001
    assert abs(order.size - 10.0) < 0.001
    assert order.status == "pending"
    assert order.placed_at is not None


def test_insert_trade(repository: Repository) -> None:
    """Should create a trade with correct entry/exit fields."""
    run = repository.create_run(mode="paper", strategy_name="ltd_v1")
    market = repository.upsert_market(
        run_id=run.id,
        betfair_market_id="1.tradetest",
        event_name="Wolves v Brentford",
    )
    entry_order = repository.insert_order(
        market_id=market.id,
        run_id=run.id,
        side="LAY",
        price=Decimal("3.10"),
        size=Decimal("10.00"),
    )
    exit_order = repository.insert_order(
        market_id=market.id,
        run_id=run.id,
        side="BACK",
        price=Decimal("5.00"),
        size=Decimal("6.20"),
    )

    trade = repository.insert_trade(
        market_id=market.id,
        run_id=run.id,
        entry_order_id=entry_order.id,
        entry_price=Decimal("3.10"),
        stake=Decimal("10.00"),
        exit_order_id=exit_order.id,
        exit_price=Decimal("5.00"),
        gross_pnl=Decimal("-12.50"),
        commission=Decimal("0.00"),
        net_pnl=Decimal("-12.50"),
        exit_reason="Goal detected",
    )

    assert isinstance(trade.id, uuid.UUID)
    assert trade.exit_reason == "Goal detected"
    assert trade.closed_at is not None
