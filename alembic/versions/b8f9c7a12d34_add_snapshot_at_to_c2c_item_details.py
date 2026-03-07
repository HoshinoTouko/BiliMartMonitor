"""Add snapshot_at to c2c_items_details for incremental snapshots

Revision ID: b8f9c7a12d34
Revises: 36e6a0c5e3d1
Create Date: 2026-03-07 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b8f9c7a12d34"
down_revision: Union[str, Sequence[str], None] = "36e6a0c5e3d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("c2c_items_details")]

    if "snapshot_at" not in columns:
        op.add_column("c2c_items_details", sa.Column("snapshot_at", sa.Text(), nullable=True))

    op.execute(
        """
        UPDATE c2c_items_details
        SET snapshot_at = COALESCE(
            snapshot_at,
            (
                SELECT COALESCE(c2c_items.updated_at, c2c_items.created_at)
                FROM c2c_items
                WHERE c2c_items.c2c_items_id = c2c_items_details.c2c_items_id
            ),
            CURRENT_TIMESTAMP
        )
        WHERE snapshot_at IS NULL OR TRIM(snapshot_at) = ''
        """
    )

    index_names = {idx.get("name") for idx in inspector.get_indexes("c2c_items_details")}
    if "idx_c2c_details_c2c_snapshot_at" not in index_names:
        op.create_index(
            "idx_c2c_details_c2c_snapshot_at",
            "c2c_items_details",
            ["c2c_items_id", "snapshot_at"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_index("idx_c2c_details_c2c_snapshot_at", table_name="c2c_items_details")
    op.drop_column("c2c_items_details", "snapshot_at")
