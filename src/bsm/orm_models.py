from __future__ import annotations

from typing import List, Optional

from sqlalchemy import ForeignKey, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class AccessUser(Base):
    __tablename__ = "access_users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(Text)
    password_hash: Mapped[Optional[str]] = mapped_column(Text)
    telegram_ids_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]", server_default=text("'[]'")
    )
    keywords_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]", server_default=text("'[]'")
    )
    roles_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]", server_default=text("'[]'")
    )
    notify_enabled: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="active", server_default=text("'active'")
    )
    created_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )

    bili_sessions: Mapped[List["BiliSession"]] = relationship(
        back_populates="access_user",
        passive_deletes=True,
    )


class BiliSession(Base):
    __tablename__ = "bili_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    login_username: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    cookies: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(
        ForeignKey("access_users.username", onupdate="CASCADE", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="active", server_default=text("'active'")
    )
    fetch_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    login_at: Mapped[Optional[str]] = mapped_column(Text)
    last_success_fetch_at: Mapped[Optional[str]] = mapped_column(Text)
    last_used_at: Mapped[Optional[str]] = mapped_column(Text)
    last_checked_at: Mapped[Optional[str]] = mapped_column(Text)
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )

    access_user: Mapped[Optional[AccessUser]] = relationship(back_populates="bili_sessions")


class C2CItem(Base):
    __tablename__ = "c2c_items"

    c2c_items_id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[Optional[str]] = mapped_column(Text)
    type: Mapped[Optional[int]] = mapped_column(Integer)
    c2c_items_name: Mapped[Optional[str]] = mapped_column(Text)
    total_items_count: Mapped[Optional[int]] = mapped_column(Integer)
    price: Mapped[Optional[int]] = mapped_column(Integer)
    show_price: Mapped[Optional[str]] = mapped_column(Text)
    show_market_price: Mapped[Optional[str]] = mapped_column(Text)
    uid: Mapped[Optional[str]] = mapped_column(Text)
    payment_time: Mapped[Optional[int]] = mapped_column(Integer)
    is_my_publish: Mapped[Optional[int]] = mapped_column(Integer)
    uface: Mapped[Optional[str]] = mapped_column(Text)
    uname: Mapped[Optional[str]] = mapped_column(Text)
    detail_blob: Mapped[Optional[bytes]] = mapped_column()
    publish_status: Mapped[Optional[int]] = mapped_column(Integer)
    sale_status: Mapped[Optional[int]] = mapped_column(Integer)
    drop_reason: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )
    snapshots: Mapped[List["C2CItemSnapshot"]] = relationship(
        back_populates="c2c_item",
        passive_deletes=True,
    )
    products: Mapped[List["Product"]] = relationship(
        secondary="c2c_items_snapshot",
        primaryjoin="C2CItem.c2c_items_id == C2CItemSnapshot.c2c_items_id",
        secondaryjoin="Product.id == C2CItemSnapshot.product_id",
        viewonly=True,
    )


class Product(Base):
    __tablename__ = "product"
    __table_args__ = (
        UniqueConstraint("blindbox_id", "items_id", "sku_id", name="uq_product_triple"),
        Index("idx_product_items_sku", "items_id", "sku_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    blindbox_id: Mapped[int] = mapped_column(Integer, nullable=False)
    items_id: Mapped[int] = mapped_column(Integer, nullable=False)
    sku_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(Text)
    img_url: Mapped[Optional[str]] = mapped_column(Text)
    market_price: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )
    snapshots: Mapped[List["C2CItemSnapshot"]] = relationship(
        back_populates="product",
        passive_deletes=True,
    )
    c2c_items: Mapped[List["C2CItem"]] = relationship(
        secondary="c2c_items_snapshot",
        primaryjoin="Product.id == C2CItemSnapshot.product_id",
        secondaryjoin="C2CItem.c2c_items_id == C2CItemSnapshot.c2c_items_id",
        viewonly=True,
    )


class C2CItemSnapshot(Base):
    __tablename__ = "c2c_items_snapshot"
    __table_args__ = (
        Index("idx_c2c_snapshot_c2c_at", "c2c_items_id", "snapshot_at"),
        Index("idx_c2c_snapshot_product_id", "product_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    c2c_items_id: Mapped[int] = mapped_column(
        ForeignKey("c2c_items.c2c_items_id", ondelete="CASCADE"),
        nullable=False,
    )
    snapshot_at: Mapped[str] = mapped_column(Text, nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id", ondelete="RESTRICT"), nullable=False)
    est_price: Mapped[Optional[int]] = mapped_column(Integer)
    c2c_item: Mapped[C2CItem] = relationship(back_populates="snapshots")
    product: Mapped[Product] = relationship(back_populates="snapshots")


class SystemMetadata(Base):
    __tablename__ = "system_metadata"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[Optional[str]] = mapped_column(
        Text, server_default=text("CURRENT_TIMESTAMP")
    )


Index("idx_c2c_items_updated_at", C2CItem.updated_at)
