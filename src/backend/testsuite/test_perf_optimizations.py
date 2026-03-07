"""Tests for auth user caching and market items query optimizations."""

import os
import sys
import tempfile
import time
import unittest

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
SRC_ROOT = os.path.join(PROJECT_ROOT, "src")
if SRC_ROOT not in sys.path:
    sys.path.insert(0, SRC_ROOT)

from bsm import db
from bsm import settings


SAMPLE_ITEMS_WITH_DETAILS = [
    {
        "c2cItemsId": 5001,
        "type": 1,
        "c2cItemsName": "Item A",
        "price": 10000,
        "showPrice": "100.00",
        "showMarketPrice": "120.00",
        "uface": "",
        "uname": "alice",
        "detailDtoList": [{"itemsId": 70, "name": "Product X", "marketPrice": 100}],
    },
    {
        "c2cItemsId": 5002,
        "type": 1,
        "c2cItemsName": "Item B",
        "price": 20000,
        "showPrice": "200.00",
        "showMarketPrice": "250.00",
        "uface": "",
        "uname": "bob",
        "detailDtoList": [{"itemsId": 70, "name": "Product X", "marketPrice": 100}],
    },
]


class AuthUserCacheTestCase(unittest.TestCase):
    """Test the in-memory TTL cache for get_access_user."""

    def setUp(self) -> None:
        self.db_fd, self.db_path = tempfile.mkstemp(prefix="bsm-cache-test-", suffix=".db")
        os.close(self.db_fd)
        self.cfg_fd, self.cfg_path = tempfile.mkstemp(prefix="bsm-cache-cfg-", suffix=".yaml")
        os.close(self.cfg_fd)
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            f.write("")
        os.environ["BSM_TESTING"] = "1"
        os.environ["BSM_DB_BACKEND"] = "sqlite"
        os.environ["BSM_TEST_DB_PATH"] = self.db_path
        os.environ["BSM_CONFIG_PATH"] = self.cfg_path
        db._reset_backend_cache()
        settings.reset_access_user_cache()
        settings.reset_public_account_settings_cache()

    def tearDown(self) -> None:
        for key in ("BSM_TESTING", "BSM_DB_BACKEND", "BSM_TEST_DB_PATH", "BSM_CONFIG_PATH"):
            os.environ.pop(key, None)
        db._reset_backend_cache()
        settings.reset_access_user_cache()
        settings.reset_public_account_settings_cache()
        for path in (self.db_path, self.cfg_path):
            if os.path.exists(path):
                os.remove(path)

    def test_get_access_user_returns_cached_result(self) -> None:
        """Second call should return cached data without hitting DB again."""
        db.upsert_access_user(username="alice", display_name="Alice", password_hash="pw1", roles=["user"])
        settings.reset_access_user_cache()

        user1 = settings.get_access_user("alice")
        self.assertIsNotNone(user1)
        self.assertEqual(user1["username"], "alice")

        # Mutate DB directly (bypass settings layer to skip cache invalidation)
        db.upsert_access_user(username="alice", display_name="Alice Changed", password_hash="pw1", roles=["user"])

        # Should still return cached value
        user2 = settings.get_access_user("alice")
        self.assertEqual(user2["display_name"], "Alice")

    def test_cache_invalidated_on_upsert(self) -> None:
        """upsert_access_user should clear cache for that user."""
        db.upsert_access_user(username="bob", display_name="Bob", password_hash="pw", roles=["user"])
        settings.reset_access_user_cache()

        settings.get_access_user("bob")  # populate cache

        # Update through settings layer (should invalidate)
        settings.upsert_access_user(username="bob", display_name="Bob Updated", password_hash="pw", roles=["user"])

        user = settings.get_access_user("bob")
        self.assertEqual(user["display_name"], "Bob Updated")

    def test_cache_invalidated_on_delete(self) -> None:
        """delete_access_user should clear cache for that user."""
        db.upsert_access_user(username="carol", display_name="Carol", password_hash="pw", roles=["user"])
        settings.reset_access_user_cache()

        user = settings.get_access_user("carol")
        self.assertIsNotNone(user)

        settings.delete_access_user("carol")
        user = settings.get_access_user("carol")
        self.assertIsNone(user)

    def test_cache_returns_none_for_missing_user(self) -> None:
        """Cache should also cache None results to avoid repeated misses."""
        user = settings.get_access_user("nonexistent")
        self.assertIsNone(user)

        # Create user directly via DB (bypass cache invalidation)
        db.upsert_access_user(username="nonexistent", password_hash="pw", roles=["user"])

        # Should still return None from cache
        user = settings.get_access_user("nonexistent")
        self.assertIsNone(user)

    def test_reset_clears_all_cache(self) -> None:
        """reset_access_user_cache should clear everything."""
        db.upsert_access_user(username="dave", password_hash="pw", roles=["user"])
        settings.reset_access_user_cache()
        settings.get_access_user("dave")

        # Mutate directly
        db.upsert_access_user(username="dave", display_name="Dave New", password_hash="pw", roles=["user"])

        # Still cached
        self.assertNotEqual(settings.get_access_user("dave")["display_name"], "Dave New")

        # After reset, should see fresh data
        settings.reset_access_user_cache()
        self.assertEqual(settings.get_access_user("dave")["display_name"], "Dave New")


class MarketItemsBatchListingCountTestCase(unittest.TestCase):
    """Test that list_market_items correctly uses batch listing counts."""

    def setUp(self) -> None:
        self.db_fd, self.db_path = tempfile.mkstemp(prefix="bsm-batch-test-", suffix=".db")
        os.close(self.db_fd)
        self.cfg_fd, self.cfg_path = tempfile.mkstemp(prefix="bsm-batch-cfg-", suffix=".yaml")
        os.close(self.cfg_fd)
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            f.write("")
        os.environ["BSM_TESTING"] = "1"
        os.environ["BSM_DB_BACKEND"] = "sqlite"
        os.environ["BSM_TEST_DB_PATH"] = self.db_path
        os.environ["BSM_CONFIG_PATH"] = self.cfg_path
        db._reset_backend_cache()

    def tearDown(self) -> None:
        for key in ("BSM_TESTING", "BSM_DB_BACKEND", "BSM_TEST_DB_PATH", "BSM_CONFIG_PATH"):
            os.environ.pop(key, None)
        db._reset_backend_cache()
        for path in (self.db_path, self.cfg_path):
            if os.path.exists(path):
                os.remove(path)

    def test_listing_counts_populated_on_market_page(self) -> None:
        """Items sharing the same items_id should show correct recent_listed_count."""
        db.save_items(SAMPLE_ITEMS_WITH_DETAILS)
        items, total, pages = db.list_market_items(page=1, limit=20)

        self.assertEqual(total, 2)
        # Both items share items_id=70, so each should have recent_listed_count=2
        for item in items:
            self.assertEqual(item["recent_listed_count"], 2)

    def test_listing_counts_with_single_detail(self) -> None:
        """Items with one valid detail row should have recent_listed_count=1."""
        db.save_items([{
            "c2cItemsId": 6001,
            "c2cItemsName": "Single Detail Item",
            "price": 5000,
            "showPrice": "50.00",
            "detailDtoList": [{"itemsId": 7001, "skuId": 7101, "marketPrice": 100}],
        }])
        items, _, _ = db.list_market_items(page=1, limit=20)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["recent_listed_count"], 1)

    def test_batch_listing_counts_function(self) -> None:
        """Direct test of get_15d_listing_counts_batch."""
        db.save_items(SAMPLE_ITEMS_WITH_DETAILS)
        counts = db.get_15d_listing_counts_batch([5001, 5002])

        # Both map to items_id=70, which has 2 listings
        self.assertEqual(counts[5001], 2)
        self.assertEqual(counts[5002], 2)

    def test_batch_listing_counts_empty_input(self) -> None:
        """Empty input should return empty dict."""
        counts = db.get_15d_listing_counts_batch([])
        self.assertEqual(counts, {})


if __name__ == "__main__":
    unittest.main()
