"""Add product/c2c_items_snapshot tables and detail_blob columns

Revision ID: e1a5c9d2b741
Revises: c4d2e8a9f1b0
Create Date: 2026-03-07 15:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e1a5c9d2b741"
down_revision: Union[str, Sequence[str], None] = "c4d2e8a9f1b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_product_v2(table_name: str) -> None:
    op.create_table(
        table_name,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("blindbox_id", sa.Integer(), nullable=False),
        sa.Column("items_id", sa.Integer(), nullable=False),
        sa.Column("sku_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("img_url", sa.Text(), nullable=True),
        sa.Column("market_price", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.Text(), nullable=True),
        sa.UniqueConstraint("blindbox_id", "items_id", "sku_id", name="uq_product_triple"),
    )


def _create_snapshot_v2(table_name: str) -> None:
    op.create_table(
        table_name,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("c2c_items_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_at", sa.Text(), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("product.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("est_price", sa.Integer(), nullable=True),
    )


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    item_columns = {c["name"] for c in inspector.get_columns("c2c_items")}
    if "detail_blob" not in item_columns:
        op.add_column("c2c_items", sa.Column("detail_blob", sa.LargeBinary(), nullable=True))
    if "detail_codec" not in item_columns:
        op.add_column("c2c_items", sa.Column("detail_codec", sa.Text(), nullable=True))

    tables = set(inspector.get_table_names())

    # product table (supports in-place upgrade from old composite-PK schema)
    if "product" not in tables:
        _create_product_v2("product")
    else:
        product_cols = {c["name"] for c in inspector.get_columns("product")}
        if "id" not in product_cols:
            _create_product_v2("product_v2")
            op.execute(
                """
                INSERT INTO product_v2 (blindbox_id, items_id, sku_id, name, img_url, market_price, created_at, updated_at)
                SELECT blindbox_id, items_id, sku_id,
                       MAX(name) AS name,
                       MAX(img_url) AS img_url,
                       MAX(market_price) AS market_price,
                       MAX(created_at) AS created_at,
                       MAX(updated_at) AS updated_at
                FROM product
                GROUP BY blindbox_id, items_id, sku_id
                """
            )
            op.drop_table("product")
            op.rename_table("product_v2", "product")

    idx_names = {idx.get("name") for idx in sa.inspect(conn).get_indexes("product")}
    if "idx_product_items_sku" not in idx_names:
        op.create_index("idx_product_items_sku", "product", ["items_id", "sku_id"], unique=False)

    # snapshot table (supports in-place upgrade from triple columns schema)
    inspector = sa.inspect(conn)
    tables = set(inspector.get_table_names())
    if "c2c_items_snapshot" not in tables:
        _create_snapshot_v2("c2c_items_snapshot")
    else:
        snap_cols = {c["name"] for c in inspector.get_columns("c2c_items_snapshot")}
        if "product_id" not in snap_cols:
            _create_snapshot_v2("c2c_items_snapshot_v2")
            if {"blindbox_id", "items_id", "sku_id"}.issubset(snap_cols):
                op.execute(
                    """
                    INSERT INTO c2c_items_snapshot_v2 (c2c_items_id, snapshot_at, product_id, est_price)
                    SELECT s.c2c_items_id, s.snapshot_at, p.id, s.est_price
                    FROM c2c_items_snapshot s
                    JOIN product p
                      ON p.blindbox_id = s.blindbox_id
                     AND p.items_id = s.items_id
                     AND p.sku_id = s.sku_id
                    WHERE s.blindbox_id IS NOT NULL
                      AND s.items_id IS NOT NULL
                      AND s.sku_id IS NOT NULL
                    """
                )
            op.drop_table("c2c_items_snapshot")
            op.rename_table("c2c_items_snapshot_v2", "c2c_items_snapshot")

    snap_idx_names = {idx.get("name") for idx in sa.inspect(conn).get_indexes("c2c_items_snapshot")}
    if "idx_c2c_snapshot_c2c_at" not in snap_idx_names:
        op.create_index("idx_c2c_snapshot_c2c_at", "c2c_items_snapshot", ["c2c_items_id", "snapshot_at"], unique=False)
    if "idx_c2c_snapshot_product_id" not in snap_idx_names:
        op.create_index("idx_c2c_snapshot_product_id", "c2c_items_snapshot", ["product_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_c2c_snapshot_product_id", table_name="c2c_items_snapshot")
    op.drop_index("idx_c2c_snapshot_c2c_at", table_name="c2c_items_snapshot")
    op.drop_table("c2c_items_snapshot")

    op.drop_index("idx_product_items_sku", table_name="product")
    op.drop_table("product")

    op.drop_column("c2c_items", "detail_codec")
    op.drop_column("c2c_items", "detail_blob")
