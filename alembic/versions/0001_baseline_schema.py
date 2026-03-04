"""baseline schema and legacy migrations

Revision ID: 0001_baseline_schema
Revises:
Create Date: 2026-03-02 00:00:00.000000
"""

from typing import Iterable

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0001_baseline_schema"
down_revision = None
branch_labels = None
depends_on = None


def _table_names(bind: sa.engine.Connection) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _table_columns(bind: sa.engine.Connection, table_name: str) -> set[str]:
    try:
        rows = bind.exec_driver_sql(f"PRAGMA table_info({table_name})").fetchall()
    except Exception:
        return set()
    return {str(row[1]) for row in rows}


def _ensure_columns(
    bind: sa.engine.Connection,
    table_name: str,
    definitions: Iterable[tuple[str, str]],
) -> None:
    existing = _table_columns(bind, table_name)
    if not existing:
        return
    for column_name, ddl in definitions:
        if column_name in existing:
            continue
        bind.exec_driver_sql(f"ALTER TABLE {table_name} ADD COLUMN {ddl}")


def _has_bili_sessions_fk(bind: sa.engine.Connection) -> bool:
    try:
        rows = bind.exec_driver_sql("PRAGMA foreign_key_list(bili_sessions)").fetchall()
    except Exception:
        return False
    for row in rows:
        if (
            len(row) > 4
            and str(row[3]) == "created_by"
            and str(row[2]) == "access_users"
            and str(row[4]) == "username"
        ):
            return True
    return False


def _create_core_tables(bind: sa.engine.Connection) -> None:
    tables = _table_names(bind)

    if "access_users" not in tables:
        op.create_table(
            "access_users",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("username", sa.Text(), nullable=False, unique=True),
            sa.Column("display_name", sa.Text()),
            sa.Column("password_hash", sa.Text()),
            sa.Column("telegram_id", sa.Text()),
            sa.Column("telegram_ids_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("keywords_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("roles_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("notify_enabled", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
            sa.Column("created_at", sa.Text(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.Text(), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        tables.add("access_users")

    if "bili_sessions" not in tables:
        op.create_table(
            "bili_sessions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("login_username", sa.Text(), nullable=False, unique=True),
            sa.Column("cookies", sa.Text(), nullable=False),
            sa.Column(
                "created_by",
                sa.Text(),
                sa.ForeignKey("access_users.username", onupdate="CASCADE", ondelete="SET NULL"),
            ),
            sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
            sa.Column("fetch_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("login_at", sa.Text()),
            sa.Column("last_success_fetch_at", sa.Text()),
            sa.Column("last_used_at", sa.Text()),
            sa.Column("last_checked_at", sa.Text()),
            sa.Column("last_error", sa.Text()),
            sa.Column("created_at", sa.Text(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.Text(), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        tables.add("bili_sessions")

    if "c2c_items" not in tables:
        op.create_table(
            "c2c_items",
            sa.Column("c2c_items_id", sa.Integer(), primary_key=True),
            sa.Column("type", sa.Integer()),
            sa.Column("c2c_items_name", sa.Text()),
            sa.Column("total_items_count", sa.Integer()),
            sa.Column("price", sa.Integer()),
            sa.Column("show_price", sa.Text()),
            sa.Column("show_market_price", sa.Text()),
            sa.Column("uid", sa.Text()),
            sa.Column("payment_time", sa.Integer()),
            sa.Column("is_my_publish", sa.Integer()),
            sa.Column("uface", sa.Text()),
            sa.Column("uname", sa.Text()),
            sa.Column("detail_json", sa.Text()),
            sa.Column("updated_at", sa.Text(), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index("idx_c2c_items_updated_at", "c2c_items", ["updated_at"], unique=False)
        tables.add("c2c_items")

    if "c2c_price_history" not in tables:
        op.create_table(
            "c2c_price_history",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("c2c_items_id", sa.Integer(), nullable=False),
            sa.Column("price", sa.Integer()),
            sa.Column("show_price", sa.Text()),
            sa.Column("recorded_at", sa.Text(), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        tables.add("c2c_price_history")

    if "c2c_items_details" not in tables:
        op.create_table(
            "c2c_items_details",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("c2c_items_id", sa.Integer(), nullable=False),
            sa.Column("items_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.Text()),
            sa.Column("img_url", sa.Text()),
            sa.Column("market_price", sa.Integer()),
        )
        op.create_index("idx_c2c_details_items_id", "c2c_items_details", ["items_id"], unique=False)
        op.create_index("idx_c2c_details_c2c_items_id", "c2c_items_details", ["c2c_items_id"], unique=False)


def upgrade() -> None:
    bind = op.get_bind()
    _create_core_tables(bind)

    _ensure_columns(
        bind,
        "access_users",
        (
            ("telegram_ids_json", "telegram_ids_json TEXT NOT NULL DEFAULT '[]'"),
            ("notify_enabled", "notify_enabled INTEGER NOT NULL DEFAULT 1"),
        ),
    )
    access_cols = _table_columns(bind, "access_users")
    if "telegram_ids_json" in access_cols:
        bind.exec_driver_sql(
            """
            UPDATE access_users
            SET telegram_ids_json = CASE
                WHEN telegram_ids_json IS NOT NULL AND TRIM(telegram_ids_json) != '' AND telegram_ids_json != '[]'
                    THEN telegram_ids_json
                WHEN telegram_id IS NULL OR TRIM(telegram_id) = ''
                    THEN '[]'
                ELSE '["' || REPLACE(REPLACE(TRIM(telegram_id), '\\', '\\\\'), '"', '\\"') || '"]'
            END
            WHERE telegram_ids_json IS NULL OR TRIM(telegram_ids_json) = '' OR telegram_ids_json = '[]'
            """
        )

    _ensure_columns(
        bind,
        "bili_sessions",
        (
            ("created_by", "created_by TEXT"),
            ("fetch_count", "fetch_count INTEGER NOT NULL DEFAULT 0"),
            ("login_at", "login_at DATETIME"),
            ("last_success_fetch_at", "last_success_fetch_at DATETIME"),
        ),
    )

    if "user_sessions" in _table_names(bind):
        _ensure_columns(
            bind,
            "user_sessions",
            (
                ("created_by", "created_by TEXT"),
                ("login_username", "login_username TEXT"),
                ("fetch_count", "fetch_count INTEGER NOT NULL DEFAULT 0"),
                ("login_at", "login_at DATETIME"),
                ("last_success_fetch_at", "last_success_fetch_at DATETIME"),
            ),
        )
        bind.exec_driver_sql(
            """
            INSERT INTO bili_sessions (
                login_username, cookies, created_by, status, fetch_count, login_at, last_success_fetch_at,
                last_used_at, last_checked_at, last_error, created_at, updated_at
            )
            SELECT
                COALESCE(NULLIF(TRIM(login_username), ''), session_name),
                cookies,
                created_by,
                COALESCE(status, 'active'),
                COALESCE(fetch_count, 0),
                login_at,
                last_success_fetch_at,
                last_used_at,
                last_checked_at,
                last_error,
                created_at,
                updated_at
            FROM user_sessions
            WHERE COALESCE(NULLIF(TRIM(COALESCE(login_username, '')), ''), NULLIF(TRIM(session_name), '')) IS NOT NULL
            ON CONFLICT(login_username) DO UPDATE SET
                cookies=excluded.cookies,
                created_by=excluded.created_by,
                status=excluded.status,
                fetch_count=excluded.fetch_count,
                login_at=excluded.login_at,
                last_success_fetch_at=excluded.last_success_fetch_at,
                last_used_at=excluded.last_used_at,
                last_checked_at=excluded.last_checked_at,
                last_error=excluded.last_error,
                updated_at=excluded.updated_at
            """
        )
        bind.exec_driver_sql("DROP TABLE user_sessions")

    if bind.dialect.name == "sqlite" and not _has_bili_sessions_fk(bind) and _table_columns(bind, "bili_sessions"):
        bind.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS bili_sessions__new (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                login_username  TEXT NOT NULL UNIQUE,
                cookies         TEXT NOT NULL,
                created_by      TEXT REFERENCES access_users(username) ON UPDATE CASCADE ON DELETE SET NULL,
                status          TEXT NOT NULL DEFAULT 'active',
                fetch_count     INTEGER NOT NULL DEFAULT 0,
                login_at        DATETIME,
                last_success_fetch_at DATETIME,
                last_used_at    DATETIME,
                last_checked_at DATETIME,
                last_error      TEXT,
                created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        bind.exec_driver_sql(
            """
            INSERT INTO bili_sessions__new (
                id, login_username, cookies, created_by, status, fetch_count, login_at, last_success_fetch_at,
                last_used_at, last_checked_at, last_error, created_at, updated_at
            )
            SELECT
                id,
                login_username,
                cookies,
                CASE
                    WHEN created_by IS NULL OR TRIM(created_by) = '' THEN NULL
                    WHEN EXISTS (SELECT 1 FROM access_users WHERE username = created_by) THEN created_by
                    ELSE NULL
                END,
                COALESCE(status, 'active'),
                COALESCE(fetch_count, 0),
                login_at,
                last_success_fetch_at,
                last_used_at,
                last_checked_at,
                last_error,
                created_at,
                updated_at
            FROM bili_sessions
            """
        )
        bind.exec_driver_sql("DROP TABLE bili_sessions")
        bind.exec_driver_sql("ALTER TABLE bili_sessions__new RENAME TO bili_sessions")


def downgrade() -> None:
    op.drop_index("idx_c2c_details_c2c_items_id", table_name="c2c_items_details")
    op.drop_index("idx_c2c_details_items_id", table_name="c2c_items_details")
    op.drop_table("c2c_items_details")
    op.drop_table("c2c_price_history")
    op.drop_index("idx_c2c_items_updated_at", table_name="c2c_items")
    op.drop_table("c2c_items")
    op.drop_table("bili_sessions")
    op.drop_table("access_users")
