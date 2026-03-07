"""Drop detail_json from c2c_items

Revision ID: 9b2c7d4e1a11
Revises: 5fd1b9c2a77a
Create Date: 2026-03-07 13:40:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9b2c7d4e1a11"
down_revision: Union[str, Sequence[str], None] = "5fd1b9c2a77a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if _has_column("c2c_items", "detail_json"):
        op.drop_column("c2c_items", "detail_json")


def downgrade() -> None:
    if not _has_column("c2c_items", "detail_json"):
        op.add_column("c2c_items", sa.Column("detail_json", sa.Text(), nullable=True))
