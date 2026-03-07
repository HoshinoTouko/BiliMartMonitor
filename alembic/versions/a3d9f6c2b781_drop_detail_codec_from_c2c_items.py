"""Drop detail_codec from c2c_items

Revision ID: a3d9f6c2b781
Revises: 9b2c7d4e1a11
Create Date: 2026-03-07 14:05:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a3d9f6c2b781"
down_revision: Union[str, Sequence[str], None] = "9b2c7d4e1a11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if _has_column("c2c_items", "detail_codec"):
        op.drop_column("c2c_items", "detail_codec")


def downgrade() -> None:
    if not _has_column("c2c_items", "detail_codec"):
        op.add_column("c2c_items", sa.Column("detail_codec", sa.Text(), nullable=True))
