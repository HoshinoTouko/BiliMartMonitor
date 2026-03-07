"""Drop market_price from c2c_items_snapshot

Revision ID: 5fd1b9c2a77a
Revises: e1a5c9d2b741
Create Date: 2026-03-07 16:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5fd1b9c2a77a"
down_revision: Union[str, Sequence[str], None] = "e1a5c9d2b741"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "c2c_items_snapshot" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("c2c_items_snapshot")}
    if "market_price" in cols:
        with op.batch_alter_table("c2c_items_snapshot") as batch_op:
            batch_op.drop_column("market_price")


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "c2c_items_snapshot" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("c2c_items_snapshot")}
    if "market_price" not in cols:
        with op.batch_alter_table("c2c_items_snapshot") as batch_op:
            batch_op.add_column(sa.Column("market_price", sa.Integer(), nullable=True))
