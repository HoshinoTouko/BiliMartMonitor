import os
import json
import gzip
import sqlite3
import sys
import tempfile
import unittest
from alembic import command
from alembic.config import Config
from sqlalchemy import update


PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
SRC_ROOT = os.path.join(PROJECT_ROOT, "src")
if SRC_ROOT not in sys.path:
    sys.path.insert(0, SRC_ROOT)

from bsm import db
from bsm import settings
from bsm.orm_models import C2CItem, C2CItemSnapshot, Product


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

    def test_save_items_normalizes_default_noface_uface(self) -> None:
        db.save_items(
            [
                {
                    "c2cItemsId": 1002,
                    "c2cItemsName": "No Face Avatar",
                    "price": 12000,
                    "showPrice": "120.00",
                    "uface": "https://i0.hdslb.com/bfs/face/member/noface.jpg",
                    "detailDtoList": [{"itemsId": 5002, "skuId": 6002, "marketPrice": 120}],
                }
            ]
        )
        item = db.get_market_item(1002)
        self.assertIsNotNone(item)
        self.assertEqual(item["uface"], "https://i0.hdslb.com/bfs/face/member/noface.jpg")

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

    def test_save_items_merges_sparse_detail_fields_without_losing_existing(self) -> None:
        db.save_items(
            [
                {
                    "c2cItemsId": 9101,
                    "c2cItemsName": "Merge Detail Fields",
                    "price": 10000,
                    "showPrice": "100.00",
                    "detailDtoList": [
                        {
                            "itemsId": 9901,
                            "skuId": 8801,
                            "blindBoxId": 7701,
                            "name": "Original Product",
                            "imgUrl": "https://example.com/original.png",
                            "marketPrice": 20000,
                            "extInfo": {"rarity": "secret"},
                        }
                    ],
                }
            ]
        )
        # Second payload is sparse and lacks imgUrl/extInfo.
        db.save_items(
            [
                {
                    "c2cItemsId": 9101,
                    "c2cItemsName": "Merge Detail Fields",
                    "price": 9900,
                    "showPrice": "99.00",
                    "detailDtoList": [
                        {
                            "itemsId": 9901,
                            "skuId": 8801,
                            "blindBoxId": 7701,
                            "name": "Original Product Renamed",
                            "marketPrice": 21000,
                        }
                    ],
                }
            ]
        )

        backend = db._require_sqlalchemy_backend()
        with backend.session() as session:
            row = session.query(C2CItem).filter(C2CItem.c2c_items_id == 9101).first()
            self.assertIsNotNone(row)
            details = db._decode_detail_blob(row.detail_blob)
        self.assertEqual(len(details), 1)
        merged = details[0]
        self.assertEqual(merged.get("name"), "Original Product Renamed")
        self.assertEqual(merged.get("imgUrl"), "https://example.com/original.png")
        self.assertEqual(merged.get("extInfo"), {"rarity": "secret"})

    def test_save_items_snapshot_follows_materialized_detail_set(self) -> None:
        db.save_items(
            [
                {
                    "c2cItemsId": 9102,
                    "c2cItemsName": "Snapshot Materialized Detail",
                    "price": 20000,
                    "showPrice": "200.00",
                    "detailDtoList": [
                        {"itemsId": 9911, "skuId": 8811, "blindBoxId": 7711, "name": "A", "marketPrice": 10000},
                        {"itemsId": 9912, "skuId": 8812, "blindBoxId": 7712, "name": "B", "marketPrice": 10000},
                    ],
                }
            ]
        )
        # Second save only sends one row; materialized detail set should still include both.
        db.save_items(
            [
                {
                    "c2cItemsId": 9102,
                    "c2cItemsName": "Snapshot Materialized Detail",
                    "price": 18000,
                    "showPrice": "180.00",
                    "detailDtoList": [
                        {"itemsId": 9911, "skuId": 8811, "blindBoxId": 7711, "name": "A2", "marketPrice": 10000},
                    ],
                }
            ]
        )

        backend = db._require_sqlalchemy_backend()
        with backend.session() as session:
            latest_ts = (
                session.query(C2CItemSnapshot.snapshot_at)
                .filter(C2CItemSnapshot.c2c_items_id == 9102)
                .order_by(C2CItemSnapshot.id.desc())
                .limit(1)
                .scalar()
            )
            latest_count = (
                session.query(C2CItemSnapshot)
                .filter(C2CItemSnapshot.c2c_items_id == 9102, C2CItemSnapshot.snapshot_at == latest_ts)
                .count()
            )
        self.assertEqual(latest_count, 2)

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

        listings_id_asc, _, _ = db.get_recent_15d_listings(50, limit=10, sort_by="ID_ASC")
        self.assertEqual([item["c2c_items_id"] for item in listings_id_asc], [3001, 3002, 3003])

        listings_id_desc, _, _ = db.get_recent_15d_listings(50, limit=10, sort_by="ID_DESC")
        self.assertEqual([item["c2c_items_id"] for item in listings_id_desc], [3003, 3002, 3001])

    def test_market_time_sort_uses_created_at(self) -> None:
        db.save_items(
            [
                {
                    "c2cItemsId": 3101,
                    "c2cItemsName": "Item 1",
                    "price": 10000,
                    "showPrice": "100.00",
                    "detailDtoList": [{"itemsId": 51, "marketPrice": 100}],
                },
                {
                    "c2cItemsId": 3102,
                    "c2cItemsName": "Item 2",
                    "price": 20000,
                    "showPrice": "200.00",
                    "detailDtoList": [{"itemsId": 51, "marketPrice": 100}],
                },
                {
                    "c2cItemsId": 3103,
                    "c2cItemsName": "Item 3",
                    "price": 30000,
                    "showPrice": "300.00",
                    "detailDtoList": [{"itemsId": 51, "marketPrice": 100}],
                },
            ]
        )

        backend = db._require_sqlalchemy_backend()
        with backend.session() as session:
            session.execute(
                update(C2CItem)
                .where(C2CItem.c2c_items_id == 3101)
                .values(created_at="2026-03-01T00:00:00Z", updated_at="2026-03-03T00:00:00Z")
            )
            session.execute(
                update(C2CItem)
                .where(C2CItem.c2c_items_id == 3102)
                .values(created_at="2026-03-03T00:00:00Z", updated_at="2026-03-01T00:00:00Z")
            )
            session.execute(
                update(C2CItem)
                .where(C2CItem.c2c_items_id == 3103)
                .values(created_at="2026-03-02T00:00:00Z", updated_at="2026-03-02T00:00:00Z")
            )
            session.commit()

        items, _, _ = db.list_market_items(limit=10, sort_by="TIME_DESC")
        ordered_ids = [row["id"] for row in items]
        self.assertEqual(ordered_ids[:3], [3102, 3103, 3101])

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

    def test_prune_orphan_old_market_data_rebuilds_product_snapshot_with_created_at(self) -> None:
        created_at = "2026-01-02T03:04:05Z"
        detail_blob = db._encode_detail_blob(
            [
                {
                    "itemsId": 9001,
                    "blindBoxId": 100,
                    "skuId": 200,
                    "name": "Legacy Product",
                    "img": "https://example.com/p.png",
                    "marketPrice": 300,
                }
            ]
        )
        backend = db._require_sqlalchemy_backend()
        with backend.session() as session:
            session.add(
                C2CItem(
                    c2c_items_id=88001,
                    c2c_items_name="Legacy Item",
                    price=12345,
                    created_at=created_at,
                    updated_at="2026-02-01T00:00:00Z",
                    detail_blob=detail_blob,
                )
            )

        result = db.prune_orphan_old_market_data()
        self.assertTrue(result["ok"])
        self.assertEqual(result["success_count"], 1)
        self.assertEqual(result["created_products"], 1)
        self.assertEqual(result["created_snapshots"], 1)

        with backend.session() as session:
            product = session.query(Product).filter(Product.items_id == 9001, Product.sku_id == 200).first()
            self.assertIsNotNone(product)
            self.assertEqual(product.created_at, created_at)
            self.assertEqual(product.updated_at, created_at)
            snap = session.query(C2CItemSnapshot).filter(C2CItemSnapshot.c2c_items_id == 88001).first()
            self.assertIsNotNone(snap)
            self.assertEqual(snap.snapshot_at, created_at)

    def test_item_details_incremental_snapshots_use_latest_for_queries(self) -> None:
        db.save_items(
            [
                {
                    "c2cItemsId": 4101,
                    "c2cItemsName": "Snapshot Item",
                    "price": 10000,
                    "showPrice": "100.00",
                    "detailDtoList": [
                        {"itemsId": 61, "name": "Product B", "marketPrice": 100},
                        {"itemsId": 62, "name": "Product C", "marketPrice": 900},
                    ],
                }
            ]
        )
        db.save_items(
            [
                {
                    "c2cItemsId": 4101,
                    "c2cItemsName": "Snapshot Item",
                    "price": 10000,
                    "showPrice": "100.00",
                    "detailDtoList": [
                        {"itemsId": 61, "name": "Product B", "marketPrice": 100},
                    ],
                }
            ]
        )

        backend = db._require_sqlalchemy_backend()
        with backend.session() as session:
            snapshot_rows = session.query(C2CItemSnapshot).filter(C2CItemSnapshot.c2c_items_id == 4101).all()
        self.assertEqual(
            len(snapshot_rows),
            4,
            "Snapshot writes should be append-only and follow the materialized detail set",
        )

        listings, _, _ = db.get_recent_15d_listings(61, page=1, limit=10, sort_by="TIME_DESC")
        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0]["c2c_items_id"], 4101)
        self.assertEqual(
            listings[0]["show_est_price"],
            "10.00",
            "Estimations should follow the latest materialized detail distribution",
        )

    def test_database_backend_uses_sqlalchemy_for_sqlite(self) -> None:
        settings = db._load_db_settings()
        backend = db._backend()

        self.assertEqual(settings["backend"], "sqlite")
        self.assertTrue(settings["db_url"].startswith("sqlite:///"))
        self.assertIsInstance(backend, db.SqlalchemyBackend)

    def test_c2c_items_schema_has_only_detail_blob(self) -> None:
        backend = db._require_sqlalchemy_backend()
        raw_conn = backend._engine.raw_connection()
        try:
            columns = {row[1] for row in raw_conn.execute("PRAGMA table_info(c2c_items)").fetchall()}
        finally:
            raw_conn.close()
        self.assertIn("detail_blob", columns)
        self.assertNotIn("detail_json", columns)
        self.assertNotIn("detail_codec", columns)

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
            "detailDtoList": [{"itemsId": 8101, "skuId": 8201, "marketPrice": 100}],
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
                    "detailDtoList": [{"itemsId": 8102, "skuId": 8202, "marketPrice": 100}],
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
        password_hash = str(user.get("password_hash") or "")
        self.assertTrue(password_hash.startswith("pbkdf2_sha256$"))
        parts = password_hash.split("$")
        self.assertEqual(len(parts), 4)
        self.assertEqual(len(parts[2]), 32)

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

    def test_database_size_report_counts_recent_rows_for_c2c_item_snapshots(self) -> None:
        db.save_items(
            [
                {
                    "c2cItemsId": 9101,
                    "c2cItemsName": "Recent bundle",
                    "price": 10000,
                    "showPrice": "100.00",
                    "detailDtoList": [
                        {"itemsId": 1, "name": "A", "marketPrice": 100},
                        {"itemsId": 2, "name": "B", "marketPrice": 200},
                    ],
                },
                {
                    "c2cItemsId": 9102,
                    "c2cItemsName": "Old bundle",
                    "price": 12000,
                    "showPrice": "120.00",
                    "detailDtoList": [
                        {"itemsId": 3, "name": "C", "marketPrice": 300},
                        {"itemsId": 4, "name": "D", "marketPrice": 400},
                        {"itemsId": 5, "name": "E", "marketPrice": 500},
                    ],
                },
            ]
        )

        backend = db._require_sqlalchemy_backend()
        with backend.session() as session:
            session.execute(
                update(C2CItem)
                .where(C2CItem.c2c_items_id == 9101)
                .values(updated_at="2026-03-06T00:00:00Z", created_at="2026-03-06T00:00:00Z")
            )
            session.execute(
                update(C2CItem)
                .where(C2CItem.c2c_items_id == 9102)
                .values(updated_at="2025-01-01T00:00:00Z", created_at="2025-01-01T00:00:00Z")
            )
            session.commit()

        report = db.get_database_size_report(days=7, top_n=50)
        snapshot_row = next((row for row in report["tables"] if row.get("name") == "c2c_items_snapshot"), None)
        self.assertIsNotNone(snapshot_row)
        self.assertEqual(int(snapshot_row["row_count"]), 5)
        self.assertEqual(int(snapshot_row["recent_rows"]), 2)


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

    def test_alembic_upgrade_initializes_init_schema(self) -> None:
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
            for required in (
                "access_users",
                "bili_sessions",
                "c2c_items",
                "product",
                "c2c_items_snapshot",
                "system_metadata",
                "alembic_version",
            ):
                self.assertIn(required, tables)
            self.assertNotIn("c2c_items_details", tables)
            self.assertNotIn("c2c_price_history", tables)

            access_columns = {row[1] for row in conn.execute("PRAGMA table_info(access_users)").fetchall()}
            self.assertIn("telegram_ids_json", access_columns)
            self.assertIn("password_hash", access_columns)
            self.assertNotIn("telegram_id", access_columns)
        finally:
            conn.close()

    def test_alembic_upgrade_records_single_init_revision(self) -> None:
        os.environ["BSM_DB_BACKEND"] = "sqlite"
        os.environ["BSM_SQLITE_PATH"] = self.db_path
        with open(self.env_path, "w", encoding="utf-8") as f:
            f.write("BSM_DB_BACKEND=sqlite\n")
            f.write(f"BSM_SQLITE_PATH={self.db_path}\n")

        cfg = Config(os.path.join(PROJECT_ROOT, "alembic.ini"))
        command.upgrade(cfg, "head")

        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "0001_init")
        finally:
            conn.close()

if __name__ == "__main__":
    unittest.main()
