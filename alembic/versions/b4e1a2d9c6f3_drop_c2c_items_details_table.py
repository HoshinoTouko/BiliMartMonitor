"""Drop legacy c2c_items_details table

Revision ID: b4e1a2d9c6f3
Revises: a3d9f6c2b781
Create Date: 2026-03-07 14:30:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b4e1a2d9c6f3"
down_revision: Union[str, Sequence[str], None] = "a3d9f6c2b781"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(table: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table in set(insp.get_table_names())


def upgrade() -> None:
    if _has_table("c2c_items_details"):
        op.drop_table("c2c_items_details")


def downgrade() -> None:
    if not _has_table("c2c_items_details"):
        op.create_table(
            "c2c_items_details",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("c2c_items_id", sa.Integer(), nullable=False),
            sa.Column("items_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.Text(), nullable=True),
            sa.Column("img_url", sa.Text(), nullable=True),
            sa.Column("market_price", sa.Integer(), nullable=True),
            sa.Column("snapshot_at", sa.Text(), nullable=True),
        )
        op.create_index("idx_c2c_details_items_id", "c2c_items_details", ["items_id"], unique=False)
        op.create_index("idx_c2c_details_c2c_items_id", "c2c_items_details", ["c2c_items_id"], unique=False)
        op.create_index(
            "idx_c2c_details_c2c_snapshot_at",
            "c2c_items_details",
            ["c2c_items_id", "snapshot_at"],
            unique=False,
        )
