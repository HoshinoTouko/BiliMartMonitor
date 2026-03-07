"""Add FK from c2c_items_snapshot.c2c_items_id to c2c_items

Revision ID: d1f3a6b8c901
Revises: c7f4a1e9d2b0
Create Date: 2026-03-07 16:40:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d1f3a6b8c901"
down_revision: Union[str, Sequence[str], None] = "c7f4a1e9d2b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(table: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table in set(insp.get_table_names())


def _has_snapshot_c2c_fk() -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for fk in insp.get_foreign_keys("c2c_items_snapshot"):
        cols = fk.get("constrained_columns") or []
        ref_table = fk.get("referred_table")
        ref_cols = fk.get("referred_columns") or []
        if cols == ["c2c_items_id"] and ref_table == "c2c_items" and ref_cols == ["c2c_items_id"]:
            return True
    return False


def upgrade() -> None:
    if not _has_table("c2c_items_snapshot") or not _has_table("c2c_items"):
        return
    if _has_snapshot_c2c_fk():
        return
    with op.batch_alter_table("c2c_items_snapshot") as batch_op:
        batch_op.create_foreign_key(
            "fk_c2c_snapshot_c2c_items_id",
            "c2c_items",
            ["c2c_items_id"],
            ["c2c_items_id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    if not _has_table("c2c_items_snapshot"):
        return
    if not _has_snapshot_c2c_fk():
        return
    with op.batch_alter_table("c2c_items_snapshot") as batch_op:
        batch_op.drop_constraint("fk_c2c_snapshot_c2c_items_id", type_="foreignkey")
