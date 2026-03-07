"""Initialize schema

Revision ID: 0001_init
Revises:
Create Date: 2026-03-08 00:20:00
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0001_init"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "access_users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("username", sa.Text(), nullable=False, unique=True),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("telegram_ids_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("keywords_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("roles_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("notify_enabled", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "bili_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("login_username", sa.Text(), nullable=False, unique=True),
        sa.Column("cookies", sa.Text(), nullable=False),
        sa.Column(
            "created_by",
            sa.Text(),
            sa.ForeignKey("access_users.username", onupdate="CASCADE", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("fetch_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("login_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("last_success_fetch_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("last_used_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("last_checked_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "c2c_items",
        sa.Column("c2c_items_id", sa.Integer(), primary_key=True),
        sa.Column("category_id", sa.Text(), nullable=True),
        sa.Column("type", sa.Integer(), nullable=True),
        sa.Column("c2c_items_name", sa.Text(), nullable=True),
        sa.Column("total_items_count", sa.Integer(), nullable=True),
        sa.Column("price", sa.Integer(), nullable=True),
        sa.Column("show_price", sa.Text(), nullable=True),
        sa.Column("show_market_price", sa.Text(), nullable=True),
        sa.Column("uid", sa.Text(), nullable=True),
        sa.Column("payment_time", sa.Integer(), nullable=True),
        sa.Column("is_my_publish", sa.Integer(), nullable=True),
        sa.Column("uface", sa.Text(), nullable=True),
        sa.Column("uname", sa.Text(), nullable=True),
        sa.Column("detail_blob", sa.LargeBinary(), nullable=True),
        sa.Column("publish_status", sa.Integer(), nullable=True),
        sa.Column("sale_status", sa.Integer(), nullable=True),
        sa.Column("drop_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("idx_c2c_items_updated_at", "c2c_items", ["updated_at"], unique=False)

    op.create_table(
        "product",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("blindbox_id", sa.Integer(), nullable=False),
        sa.Column("items_id", sa.Integer(), nullable=False),
        sa.Column("sku_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("img_url", sa.Text(), nullable=True),
        sa.Column("market_price", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("blindbox_id", "items_id", "sku_id", name="uq_product_triple"),
    )
    op.create_index("idx_product_items_sku", "product", ["items_id", "sku_id"], unique=False)

    op.create_table(
        "c2c_items_snapshot",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "c2c_items_id",
            sa.Integer(),
            sa.ForeignKey("c2c_items.c2c_items_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("snapshot_at", sa.TIMESTAMP(), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("product.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("est_price", sa.Integer(), nullable=True),
    )
    op.create_index("idx_c2c_snapshot_c2c_at", "c2c_items_snapshot", ["c2c_items_id", "snapshot_at"], unique=False)
    op.create_index("idx_c2c_snapshot_product_id", "c2c_items_snapshot", ["product_id"], unique=False)

    op.create_table(
        "system_metadata",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )


def downgrade() -> None:
    op.drop_table("system_metadata")
    op.drop_index("idx_c2c_snapshot_product_id", table_name="c2c_items_snapshot")
    op.drop_index("idx_c2c_snapshot_c2c_at", table_name="c2c_items_snapshot")
    op.drop_table("c2c_items_snapshot")
    op.drop_index("idx_product_items_sku", table_name="product")
    op.drop_table("product")
    op.drop_index("idx_c2c_items_updated_at", table_name="c2c_items")
    op.drop_table("c2c_items")
    op.drop_table("bili_sessions")
    op.drop_table("access_users")
