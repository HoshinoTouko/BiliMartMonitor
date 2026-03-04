import os
import sqlite3
import sys
import tempfile
import unittest
from alembic import command
from alembic.config import Config


PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
SRC_ROOT = os.path.join(PROJECT_ROOT, "src")
if SRC_ROOT not in sys.path:
    sys.path.insert(0, SRC_ROOT)

from bsm import db
from bsm import settings


class DatabaseTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.db_fd, self.db_path = tempfile.mkstemp(prefix="bsm-test-", suffix=".db")
        os.close(self.db_fd)
        self.env_fd, self.env_path = tempfile.mkstemp(prefix="bsm-env-", suffix=".env")
        os.close(self.env_fd)
        self.cfg_fd, self.cfg_path = tempfile.mkstemp(prefix="bsm-config-", suffix=".yaml")
        os.close(self.cfg_fd)
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            f.write("")
        os.environ["BSM_TESTING"] = "1"
        os.environ["BSM_DB_BACKEND"] = "sqlite"
        os.environ["BSM_TEST_DB_PATH"] = self.db_path
        os.environ["BSM_ENV_PATH"] = self.env_path
        os.environ["BSM_CONFIG_PATH"] = self.cfg_path
        db._reset_backend_cache()
        db.clear_bili_sessions()

    def tearDown(self) -> None:
        for key in (
            "BSM_TESTING",
            "BSM_DB_BACKEND",
            "BSM_TEST_DB_PATH",
            "BSM_DB_PATH",
            "BSM_ENV_PATH",
            "BSM_CONFIG_PATH",
            "BSM_SCAN_MODE",
            "BSM_TELEGRAM_CHAT_IDS",
            "BSM_TELEGRAM_ADMIN_CHAT_IDS",
            "BSM_TELEGRAM_HEARTBEAT_CHAT_IDS",
        ):
            os.environ.pop(key, None)
        db._reset_backend_cache()
        settings.reset_public_account_settings_cache()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        if os.path.exists(self.env_path):
            os.remove(self.env_path)
        if os.path.exists(self.cfg_path):
            os.remove(self.cfg_path)

    def test_save_items_and_search(self) -> None:
        saved, inserted = db.save_items(
            [
                {
                    "c2cItemsId": 1001,
                    "type": 1,
                    "c2cItemsName": "洛琪希 手办",
                    "totalItemsCount": 1,
                    "price": 10000,
                    "showPrice": "100.00",
                    "showMarketPrice": "120.00",
                    "uid": "u1",
                    "paymentTime": 1,
                    "isMyPublish": False,
                    "uface": " avatar ",
                    "uname": "alice",
                    "detailDtoList": [{"img": "https://example.com/1.png"}],
                }
            ]
        )

        self.assertEqual(saved, 1)
        self.assertEqual(inserted, 1)
        self.assertEqual(db.count_items(), 1)

        items, total_count, total_pages = db.search_items_by_pattern("洛琪希", limit=10, page=1)
        self.assertEqual(total_count, 1)
        self.assertEqual(total_pages, 1)
        self.assertEqual(items[0]["id"], 1001)

    def test_market_item_bundled_items(self) -> None:
        db.save_items(
            [
                {
                    "c2cItemsId": 2001,
                    "type": 1,
                    "c2cItemsName": "等3个商品",
                    "showPrice": "300.00",
                    "detailDtoList": [
                        {"itemsId": 10, "name": "item A"},
                        {"itemsId": 11, "name": "item B"}
                    ],
                }
            ]
        )
        item = db.get_market_item(2001)
        self.assertIsNotNone(item)
        self.assertIn("bundled_items", item)
        self.assertEqual(len(item["bundled_items"]), 2)
        self.assertEqual(item["bundled_items"][0]["name"], "item A")

    def test_get_recent_15d_listings_sort_by(self) -> None:
        db.save_items(
            [
                {
                    "c2cItemsId": 3001,
                    "c2cItemsName": "Item 1",
                    "price": 10000,
                    "showPrice": "100.00",
                    "detailDtoList": [{"itemsId": 50, "marketPrice": 100}],
                },
                {
                    "c2cItemsId": 3002,
                    "c2cItemsName": "Item 2",
                    "price": 20000,
                    "showPrice": "200.00",
                    "detailDtoList": [{"itemsId": 50, "marketPrice": 100}],
                },
                {
                    "c2cItemsId": 3003,
                    "c2cItemsName": "Item 3",
                    "price": 15000,
                    "showPrice": "150.00",
                    "detailDtoList": [{"itemsId": 50, "marketPrice": 100}],
                }
            ]
        )

        listings_asc, _, _ = db.get_recent_15d_listings(50, limit=10, sort_by="PRICE_ASC")
        self.assertEqual(len(listings_asc), 3)
        self.assertEqual(listings_asc[0]["c2c_items_id"], 3001)
        self.assertEqual(listings_asc[1]["c2c_items_id"], 3003)
        self.assertEqual(listings_asc[2]["c2c_items_id"], 3002)

        listings_desc, _, _ = db.get_recent_15d_listings(50, limit=10, sort_by="PRICE_DESC")
        self.assertEqual(listings_desc[1]["c2c_items_id"], 3003)
        self.assertEqual(listings_desc[2]["c2c_items_id"], 3001)

    def test_get_product_metadata_and_price_history(self) -> None:
        db.save_items(
            [
                {
                    "c2cItemsId": 4001,
                    "c2cItemsName": "Product A Bundle 1",
                    "price": 10000,
                    "showPrice": "100.00",
                    "detailDtoList": [{"itemsId": 60, "name": "Product A", "marketPrice": 120}],
                },
                {
                    "c2cItemsId": 4002,
                    "c2cItemsName": "Product A Bundle 2",
                    "price": 15000,
                    "showPrice": "150.00",
                    "detailDtoList": [{"itemsId": 60, "name": "Product A", "marketPrice": 120}],
                }
            ]
        )

        meta = db.get_product_metadata(60)
        self.assertIsNotNone(meta)
        self.assertEqual(meta["items_id"], 60)
        self.assertEqual(meta["name"], "Product A")
        self.assertEqual(meta["price_min"], 10000)
        self.assertEqual(meta["price_max"], 15000)
        self.assertEqual(meta["show_price_min"], "100.00")
        self.assertEqual(meta["show_price_max"], "150.00")
        self.assertEqual(meta["recent_listed_count"], 2)

        history = db.get_product_price_history(60)
        self.assertEqual(len(history), 2)
        prices = [h["price"] for h in history]
        self.assertIn(10000, prices)
        self.assertIn(15000, prices)

    def test_database_backend_uses_sqlalchemy_for_sqlite(self) -> None:
        settings = db._load_db_settings()
        backend = db._backend()

        self.assertEqual(settings["backend"], "sqlite")
        self.assertTrue(settings["db_url"].startswith("sqlite:///"))
        self.assertIsInstance(backend, db.SqlalchemyBackend)

    def test_runtime_config_reads_price_and_discount_filters(self) -> None:
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            f.write(
                "price_filters:\n"
                "  - 0-2000\n"
                "  - 2000-3000\n"
                "discount_filters:\n"
                "  - 80-100\n"
                "sort_type: PRICE_ASC\n"
            )

        cfg = settings.load_runtime_config()

        self.assertEqual(cfg["price_filters"], ["0-2000", "2000-3000"])
        self.assertEqual(cfg["discount_filters"], ["80-100"])
        self.assertEqual(cfg["sort_type"], "PRICE_ASC")

    def test_filter_new_items_only_returns_missing_rows(self) -> None:
        existing = {
            "c2cItemsId": 1001,
            "c2cItemsName": "Existing",
            "price": 10000,
            "showPrice": "100.00",
            "detailDtoList": [],
        }
        db.save_items([existing])

        new_items = db.filter_new_items(
            [
                existing,
                {
                    "c2cItemsId": 1002,
                    "c2cItemsName": "New",
                    "price": 12000,
                    "showPrice": "120.00",
                    "detailDtoList": [],
                },
            ]
        )

        self.assertEqual(len(new_items), 1)
        self.assertEqual(new_items[0]["c2cItemsId"], 1002)

    def test_sessions_rotate_by_last_used(self) -> None:
        db.upsert_access_user(username="admin", roles=["admin"])
        db.save_bili_session("cookie-a", login_username="bili-a", created_by="admin")
        db.save_bili_session("cookie-b", login_username="bili-b")

        first = db.load_next_bili_session()
        second = db.load_next_bili_session()

        self.assertEqual(first["login_username"], "bili-a")
        self.assertEqual(first["created_by"], "admin")
        self.assertEqual(second["login_username"], "bili-b")
        self.assertTrue(db.has_active_bili_session())

    def test_recent_error_sessions_respect_cooldown(self) -> None:
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            f.write("bili_session_cooldown_seconds: 60\n")

        db.upsert_access_user(username="admin", roles=["admin"])
        db.save_bili_session("cookie-a", login_username="bili-a", created_by="admin")
        db.save_bili_session("cookie-b", login_username="bili-b")
        db.mark_bili_session_result("bili-a", "rate limited")

        selected = db.load_next_bili_session()

        self.assertEqual(selected["login_username"], "bili-b")

        db.mark_bili_session_result("bili-b", "timeout")

        self.assertFalse(db.has_active_bili_session())

    def test_runtime_config_reads_bili_session_settings(self) -> None:
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            f.write(
                "bili_session_pick_mode: random\n"
                "bili_session_cooldown_seconds: 15\n"
            )

        cfg = settings.load_runtime_config()

        self.assertEqual(cfg["bili_session_pick_mode"], "random")
        self.assertEqual(cfg["bili_session_cooldown_seconds"], 15)

    def test_session_stats_and_logout_are_persisted(self) -> None:
        db.upsert_access_user(username="admin", roles=["admin"])
        db.save_bili_session("cookie-a", login_username="bili-a", created_by="admin")
        db.record_bili_session_fetch_success("bili-a", fetched_count=7)

        sessions = db.list_bili_sessions(status=None)
        session = sessions[0]

        self.assertEqual(session["fetch_count"], 7)
        self.assertEqual(session["login_username"], "bili-a")
        self.assertIsNotNone(session["login_at"])
        self.assertIsNotNone(session["last_success_fetch_at"])

        db.delete_bili_session("bili-a")

        sessions = db.list_bili_sessions(status=None)
        self.assertEqual(sessions, [])

    def test_bili_session_created_by_requires_existing_access_user(self) -> None:
        with self.assertRaises(Exception):
            db.save_bili_session("cookie-a", login_username="bili-a", created_by="missing-user")

    def test_bili_session_created_by_is_cleared_when_access_user_is_deleted(self) -> None:
        db.upsert_access_user(username="admin", roles=["admin"])
        db.save_bili_session("cookie-a", login_username="bili-a", created_by="admin")

        db.delete_access_user("admin")

        sessions = db.list_bili_sessions(status=None)
        self.assertEqual(sessions[0]["created_by"], None)

    def test_access_users_are_persisted(self) -> None:
        db.upsert_access_user(
            username="admin",
            display_name="Admin",
            password_hash="hashed",
            telegram_ids=["123456"],
            keywords=["无职转生", "洛琪希"],
            roles=["admin", "operator"],
        )

        user = db.get_access_user("admin")

        self.assertIsNotNone(user)
        self.assertEqual(user["telegram_ids"], ["123456"])
        self.assertEqual(user["keywords"], ["无职转生", "洛琪希"])
        self.assertEqual(user["roles"], ["admin", "operator"])

    def test_runtime_settings_are_written_to_yaml_and_ignore_env(self) -> None:
        os.environ["BSM_SCAN_MODE"] = "continue"

        initial_cfg = settings.load_runtime_config()
        self.assertEqual(initial_cfg["scan_mode"], "latest")

        settings.set_mode("continue_until_repeat")

        cfg = settings.load_runtime_config()

        self.assertEqual(cfg["scan_mode"], "continue_until_repeat")
        with open(self.cfg_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("scan_mode: continue_until_repeat", content)
        with open(self.env_path, "r", encoding="utf-8") as f:
            env_content = f.read()
        self.assertNotIn("BSM_SCAN_MODE=continue_until_repeat", env_content)

    def test_public_account_settings_cache_and_reset(self) -> None:
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            f.write("interval: 20\n")

        first = settings.get_public_account_settings()
        self.assertEqual(first["interval"], 20)

        with open(self.cfg_path, "w", encoding="utf-8") as f:
            f.write("interval: 45\n")

        cached = settings.get_public_account_settings()
        self.assertEqual(cached["interval"], 20)

        settings.reset_public_account_settings_cache()
        refreshed = settings.get_public_account_settings()
        self.assertEqual(refreshed["interval"], 45)


class AlembicMigrationTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.db_fd, self.db_path = tempfile.mkstemp(prefix="bsm-alembic-test-", suffix=".db")
        os.close(self.db_fd)
        self.env_fd, self.env_path = tempfile.mkstemp(prefix="bsm-alembic-env-", suffix=".env")
        os.close(self.env_fd)
        os.environ["BSM_ENV_PATH"] = self.env_path
        db._reset_backend_cache()

    def tearDown(self) -> None:
        os.environ.pop("BSM_ENV_PATH", None)
        os.environ.pop("BSM_DB_BACKEND", None)
        os.environ.pop("BSM_SQLITE_PATH", None)
        db._reset_backend_cache()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        if os.path.exists(self.env_path):
            os.remove(self.env_path)

    def test_alembic_upgrade_migrates_legacy_user_sessions(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                CREATE TABLE access_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    display_name TEXT,
                    password_hash TEXT,
                    telegram_id TEXT,
                    keywords_json TEXT NOT NULL DEFAULT '[]',
                    roles_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                INSERT INTO access_users (username, telegram_id, keywords_json, roles_json)
                VALUES ('admin', '123456', '[]', '[\"admin\"]')
                """
            )
            conn.execute(
                """
                CREATE TABLE user_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_name TEXT,
                    login_username TEXT,
                    cookies TEXT NOT NULL,
                    created_by TEXT,
                    status TEXT,
                    fetch_count INTEGER,
                    login_at DATETIME,
                    last_success_fetch_at DATETIME,
                    last_used_at DATETIME,
                    last_checked_at DATETIME,
                    last_error TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                INSERT INTO user_sessions (
                    session_name, login_username, cookies, created_by, status, fetch_count,
                    login_at, last_success_fetch_at, last_used_at, last_checked_at, last_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "legacy-name",
                    "",
                    "cookie-a",
                    "admin",
                    "active",
                    5,
                    "2026-03-01T00:00:00Z",
                    "2026-03-01T01:00:00Z",
                    None,
                    None,
                    None,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        os.environ["BSM_DB_BACKEND"] = "sqlite"
        os.environ["BSM_SQLITE_PATH"] = self.db_path
        
        with open(self.env_path, "w", encoding="utf-8") as f:
            f.write("BSM_DB_BACKEND=sqlite\n")
            f.write(f"BSM_SQLITE_PATH={self.db_path}\n")

        cfg = Config(os.path.join(PROJECT_ROOT, "alembic.ini"))
        command.upgrade(cfg, "head")

        conn = sqlite3.connect(self.db_path)
        try:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("bili_sessions", tables)
            self.assertNotIn("user_sessions", tables)

            access_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(access_users)").fetchall()
            }
            self.assertIn("telegram_ids_json", access_columns)
            self.assertIn("notify_enabled", access_columns)

            migrated = conn.execute(
                """
                SELECT login_username, cookies, created_by, fetch_count, login_at, last_success_fetch_at
                FROM bili_sessions
                """
            ).fetchone()
            self.assertIsNotNone(migrated)
            self.assertEqual(migrated[0], "legacy-name")
            self.assertEqual(migrated[1], "cookie-a")
            self.assertEqual(migrated[2], "admin")
            self.assertEqual(migrated[3], 5)
            self.assertEqual(migrated[4], "2026-03-01T00:00:00Z")
            self.assertEqual(migrated[5], "2026-03-01T01:00:00Z")

            telegram_ids_json = conn.execute(
                "SELECT telegram_ids_json FROM access_users WHERE username = 'admin'"
            ).fetchone()
            self.assertEqual(telegram_ids_json[0], "[\"123456\"]")
        finally:
            conn.close()

if __name__ == "__main__":
    unittest.main()
