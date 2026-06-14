"""SQLAlchemy ORM models for the Betfair LTD bot.

All tables live in the ``trading`` schema in PostgreSQL.
UUID primary keys are generated in Python (uuid.uuid4) to avoid
requiring the uuid-ossp extension.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base with ``trading`` schema default."""


class Run(Base):
    """Represents one bot session (backtest, paper, or live)."""

    __tablename__ = "runs"
    __table_args__ = {"schema": "trading"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    strategy_name: Mapped[str] = mapped_column(String(50), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    total_pnl: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    commission_paid: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)

    markets: Mapped[list[Market]] = relationship(
        "Market", back_populates="run", lazy="raise"
    )


class Market(Base):
    """One row per Betfair market processed in a run."""

    __tablename__ = "markets"
    __table_args__ = {"schema": "trading"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trading.runs.id"), nullable=False
    )
    betfair_market_id: Mapped[str] = mapped_column(
        String(50), nullable=False, unique=True
    )
    event_name: Mapped[str] = mapped_column(String(255), nullable=False)
    market_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="MATCH_ODDS"
    )
    kick_off: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )

    run: Mapped[Run] = relationship("Run", back_populates="markets")
    ticks: Mapped[list[Tick]] = relationship(
        "Tick", back_populates="market", lazy="raise"
    )
    orders: Mapped[list[Order]] = relationship(
        "Order", back_populates="market", lazy="raise"
    )
    trades: Mapped[list[Trade]] = relationship(
        "Trade", back_populates="market", lazy="raise"
    )


class Tick(Base):
    """Price snapshot at every streaming update for the draw runner."""

    __tablename__ = "ticks"
    __table_args__ = {"schema": "trading"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    market_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trading.markets.id"), nullable=False
    )
    draw_lay_price: Mapped[float] = mapped_column(
        Numeric(6, 2), nullable=False
    )
    draw_back_price: Mapped[float] = mapped_column(
        Numeric(6, 2), nullable=False
    )
    volume_matched: Mapped[int] = mapped_column(BigInteger, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )

    market: Mapped[Market] = relationship("Market", back_populates="ticks")


class Order(Base):
    """Every order placed (real or simulated)."""

    __tablename__ = "orders"
    __table_args__ = {"schema": "trading"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    market_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trading.markets.id"), nullable=False
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trading.runs.id"), nullable=False
    )
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    price: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False)
    size: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )
    betfair_bet_id: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    placed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    matched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    market: Mapped[Market] = relationship("Market", back_populates="orders", lazy="raise")


class Trade(Base):
    """Completed round-trips: entry lay + exit back on the same market."""

    __tablename__ = "trades"
    __table_args__ = {"schema": "trading"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    market_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trading.markets.id"), nullable=False
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trading.runs.id"), nullable=False
    )
    entry_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trading.orders.id"), nullable=False
    )
    exit_order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trading.orders.id"), nullable=True
    )
    entry_price: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False)
    exit_price: Mapped[float | None] = mapped_column(
        Numeric(8, 2), nullable=True
    )
    stake: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    gross_pnl: Mapped[float | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    commission: Mapped[float | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    net_pnl: Mapped[float | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    exit_reason: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    market: Mapped[Market] = relationship("Market", back_populates="trades", lazy="raise")
