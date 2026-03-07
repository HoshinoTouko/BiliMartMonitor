"""Backfill c2c_items_details snapshots from c2c_price_history timestamps

Revision ID: c4d2e8a9f1b0
Revises: b8f9c7a12d34
Create Date: 2026-03-07 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c4d2e8a9f1b0"
down_revision: Union[str, Sequence[str], None] = "b8f9c7a12d34"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # For each c2c_items_id, replicate the latest known detail composition across
    # all historical price timestamps so details can be queried as time snapshots.
    op.execute(
        """
        WITH latest_snapshot AS (
            SELECT c2c_items_id, MAX(snapshot_at) AS snapshot_at
            FROM c2c_items_details
            WHERE snapshot_at IS NOT NULL AND TRIM(snapshot_at) != ''
            GROUP BY c2c_items_id
        ),
        base_details AS (
            SELECT d.c2c_items_id, d.items_id, d.name, d.img_url, d.market_price
            FROM c2c_items_details d
            JOIN latest_snapshot ls
              ON ls.c2c_items_id = d.c2c_items_id
             AND ls.snapshot_at = d.snapshot_at
        ),
        history_points AS (
            SELECT DISTINCT c2c_items_id, recorded_at
            FROM c2c_price_history
            WHERE recorded_at IS NOT NULL AND TRIM(recorded_at) != ''
        )
        INSERT INTO c2c_items_details (c2c_items_id, items_id, name, img_url, market_price, snapshot_at)
        SELECT
            b.c2c_items_id,
            b.items_id,
            b.name,
            b.img_url,
            b.market_price,
            h.recorded_at
        FROM base_details b
        JOIN history_points h ON h.c2c_items_id = b.c2c_items_id
        WHERE NOT EXISTS (
            SELECT 1
            FROM c2c_items_details e
            WHERE e.c2c_items_id = b.c2c_items_id
              AND e.items_id = b.items_id
              AND COALESCE(e.name, '') = COALESCE(b.name, '')
              AND COALESCE(e.img_url, '') = COALESCE(b.img_url, '')
              AND COALESCE(e.market_price, -1) = COALESCE(b.market_price, -1)
              AND e.snapshot_at = h.recorded_at
        )
        """
    )


def downgrade() -> None:
    # Data migration is intentionally not reversed to avoid deleting valid
    # snapshots that may have been written after upgrade.
    pass
