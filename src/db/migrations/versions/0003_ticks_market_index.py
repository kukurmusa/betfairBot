"""Add composite index on ticks(market_id, recorded_at).

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-22
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add composite index for efficient per-market tick queries."""
    op.create_index(
        "idx_ticks_market_recorded",
        "ticks",
        ["market_id", "recorded_at"],
        schema="trading",
    )


def downgrade() -> None:
    """Drop the composite ticks index."""
    op.drop_index("idx_ticks_market_recorded", table_name="ticks", schema="trading")
