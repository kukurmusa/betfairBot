"""Add orders and trades tables.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create orders and trades tables."""
    # --- orders ---
    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "market_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("price", sa.Numeric(8, 2), nullable=False),
        sa.Column("size", sa.Numeric(10, 2), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("betfair_bet_id", sa.String(50), nullable=True),
        sa.Column("placed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["market_id"], ["trading.markets.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["trading.runs.id"]),
        schema="trading",
    )

    op.create_index(
        "idx_orders_market",
        "orders",
        ["market_id"],
        schema="trading",
    )
    op.create_index(
        "idx_orders_status",
        "orders",
        ["status"],
        schema="trading",
    )

    # --- trades ---
    op.create_table(
        "trades",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "market_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "entry_order_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "exit_order_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("entry_price", sa.Numeric(8, 2), nullable=False),
        sa.Column("exit_price", sa.Numeric(8, 2), nullable=True),
        sa.Column("stake", sa.Numeric(10, 2), nullable=False),
        sa.Column("gross_pnl", sa.Numeric(12, 2), nullable=True),
        sa.Column("commission", sa.Numeric(10, 2), nullable=True),
        sa.Column("net_pnl", sa.Numeric(12, 2), nullable=True),
        sa.Column("exit_reason", sa.String(50), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["market_id"], ["trading.markets.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["trading.runs.id"]),
        sa.ForeignKeyConstraint(["entry_order_id"], ["trading.orders.id"]),
        sa.ForeignKeyConstraint(["exit_order_id"], ["trading.orders.id"]),
        schema="trading",
    )

    op.create_index(
        "idx_trades_market",
        "trades",
        ["market_id"],
        schema="trading",
    )
    op.create_index(
        "idx_trades_closed_at",
        "trades",
        ["closed_at"],
        schema="trading",
    )


def downgrade() -> None:
    """Drop orders and trades tables."""
    op.drop_index("idx_trades_closed_at", table_name="trades", schema="trading")
    op.drop_index("idx_trades_market", table_name="trades", schema="trading")
    op.drop_table("trades", schema="trading")
    op.drop_index("idx_orders_status", table_name="orders", schema="trading")
    op.drop_index("idx_orders_market", table_name="orders", schema="trading")
    op.drop_table("orders", schema="trading")
