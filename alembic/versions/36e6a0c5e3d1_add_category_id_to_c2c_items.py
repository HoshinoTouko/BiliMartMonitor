"""Add category_id to C2CItem

Revision ID: 36e6a0c5e3d1
Revises: f94b7650f2af
Create Date: 2026-03-04 15:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "36e6a0c5e3d1"
down_revision: Union[str, Sequence[str], None] = "f94b7650f2af"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("c2c_items")]

    if "category_id" not in columns:
        op.add_column("c2c_items", sa.Column("category_id", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("c2c_items", "category_id")
