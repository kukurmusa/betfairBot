"""Initial schema — trading schema, runs, markets, ticks tables.

Revision ID: 0001
Revises: None
Create Date: 2026-06-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create the trading schema
    op.execute("CREATE SCHEMA IF NOT EXISTS trading")

    # --- runs ---
    op.create_table(
        "runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("strategy_name", sa.String(50), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_pnl", sa.Numeric(10, 4), nullable=True),
        sa.Column("commission_paid", sa.Numeric(10, 4), nullable=True),
        schema="trading",
    )

    # --- markets ---
    op.create_table(
        "markets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("betfair_market_id", sa.String(50), nullable=False, unique=True),
        sa.Column("event_name", sa.String(255), nullable=False),
        sa.Column("market_type", sa.String(50), nullable=False),
        sa.Column("kick_off", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["trading.runs.id"]),
        schema="trading",
    )

    # --- ticks ---
    op.create_table(
        "ticks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("market_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("draw_lay_price", sa.Numeric(6, 2), nullable=False),
        sa.Column("draw_back_price", sa.Numeric(6, 2), nullable=False),
        sa.Column("volume_matched", sa.BigInteger, nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["market_id"], ["trading.markets.id"]),
        schema="trading",
    )


def downgrade() -> None:
    op.drop_table("ticks", schema="trading")
    op.drop_table("markets", schema="trading")
    op.drop_table("runs", schema="trading")
    op.execute("DROP SCHEMA IF EXISTS trading")
