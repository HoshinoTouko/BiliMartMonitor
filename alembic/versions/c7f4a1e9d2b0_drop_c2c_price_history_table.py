"""Drop legacy c2c_price_history table

Revision ID: c7f4a1e9d2b0
Revises: b4e1a2d9c6f3
Create Date: 2026-03-07 14:45:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c7f4a1e9d2b0"
down_revision: Union[str, Sequence[str], None] = "b4e1a2d9c6f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(table: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table in set(insp.get_table_names())


def upgrade() -> None:
    if _has_table("c2c_price_history"):
        op.drop_table("c2c_price_history")


def downgrade() -> None:
    if not _has_table("c2c_price_history"):
        op.create_table(
            "c2c_price_history",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("c2c_items_id", sa.Integer(), nullable=False),
            sa.Column("price", sa.Integer(), nullable=True),
            sa.Column("show_price", sa.Text(), nullable=True),
            sa.Column("recorded_at", sa.Text(), nullable=True),
        )
        op.create_index("idx_c2c_price_history_c2c_items_id", "c2c_price_history", ["c2c_items_id"], unique=False)
