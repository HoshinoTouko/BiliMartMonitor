"""
Integration tests for the market API router endpoints.
Uses FastAPI's TestClient (starlette) to test HTTP routes directly.
"""
import os
import sys
import tempfile
import unittest

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
SRC_ROOT = os.path.join(PROJECT_ROOT, "src")

# Ensure src/ (bsm + backend package) is importable
if SRC_ROOT not in sys.path:
    sys.path.insert(0, SRC_ROOT)


class MarketRouterTestCase(unittest.TestCase):
    """Test the FastAPI /api/market/* routes end-to-end via TestClient."""

    def setUp(self) -> None:
        self.db_fd, self.db_path = tempfile.mkstemp(prefix="bsm-router-test-", suffix=".db")
        os.close(self.db_fd)
        self.env_fd, self.env_path = tempfile.mkstemp(prefix="bsm-env-", suffix=".env")
        os.close(self.env_fd)
        os.environ["BSM_TESTING"] = "1"
        os.environ["BSM_DB_BACKEND"] = "sqlite"
        os.environ["BSM_TEST_DB_PATH"] = self.db_path
        os.environ["BSM_ENV_PATH"] = self.env_path

        # Import app AFTER env vars are set so db.py uses the temp database
        # Use importlib to force reload in case another test already imported it
        import importlib
        import bsm.db as db_mod
        importlib.reload(db_mod)
        import backend.routers.market as market_mod
        importlib.reload(market_mod)

        from backend.main import app
        from fastapi.testclient import TestClient
        from bsm.settings import upsert_access_user

        self.app = app
        self.client = TestClient(self.app, raise_server_exceptions=True)
        
        # Seed test user
        self.auth = ("testadmin", "admin")
        upsert_access_user(
            username="testadmin",
            display_name="Test Admin",
            password_hash="admin",
            roles=["admin"],
            status="active",
        )

        # Populate test data via db module directly
        from bsm.db import save_items
        self.save_items = save_items
        self.sample_items = [
            {
                "c2cItemsId": 3001,
                "categoryId": "2312",
                "type": 1,
                "c2cItemsName": "洛琪希 手办 GSC",
                "totalItemsCount": 1,
                "price": 10000,
                "showPrice": "100.00",
                "showMarketPrice": "130.00",
                "uid": "u1",
                "paymentTime": 1,
                "isMyPublish": False,
                "uface": "https://example.com/face.jpg",
                "uname": "alice",
                "detailDtoList": [{"itemsId": 50, "name": "Test Bundled Item", "img": "https://example.com/item.png"}],
            },
            {
                "c2cItemsId": 3002,
                "categoryId": "2066",
                "type": 1,
                "c2cItemsName": "灰原哀 手办 ALTER",
                "totalItemsCount": 1,
                "price": 28000,
                "showPrice": "280.00",
                "showMarketPrice": "350.00",
                "uid": "u2",
                "paymentTime": 2,
                "isMyPublish": False,
                "uface": "",
                "uname": "bob",
                "detailDtoList": [],
            },
        ]

    def tearDown(self) -> None:
        for key in ("BSM_TESTING", "BSM_DB_BACKEND", "BSM_TEST_DB_PATH", "BSM_DB_PATH", "BSM_ENV_PATH"):
            os.environ.pop(key, None)
        for path in (self.db_path, self.env_path):
            if os.path.exists(path):
                os.remove(path)

    # ------------------------------------------------------------------
    # GET /api/market/items
    # ------------------------------------------------------------------

    def test_list_items_empty(self) -> None:
        resp = self.client.get("/api/market/items", auth=self.auth)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("items", body)
        self.assertIn("pagination", body)
        self.assertEqual(body["items"], [])
        self.assertEqual(body["pagination"]["total_count"], 0)
        self.assertEqual(body["pagination"]["total_pages"], 0)

    def test_list_items_returns_data(self) -> None:
        self.save_items(self.sample_items)
        resp = self.client.get("/api/market/items?page=1&limit=12", auth=self.auth)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["pagination"]["total_count"], 2)
        self.assertEqual(len(body["items"]), 2)
        # Fields present
        item = body["items"][0]
        for field in ("id", "name", "show_price", "img_url", "updated_at"):
            self.assertIn(field, item)

    def test_list_items_pagination_limit(self) -> None:
        self.save_items(self.sample_items)
        resp = self.client.get("/api/market/items?page=1&limit=1", auth=self.auth)
        body = resp.json()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["pagination"]["total_count"], 2)
        self.assertEqual(body["pagination"]["total_pages"], 2)
        self.assertEqual(body["pagination"]["limit"], 1)

    def test_list_items_filters_by_categories(self) -> None:
        self.save_items(self.sample_items)
        resp = self.client.get("/api/market/items?category=2312,2331", auth=self.auth)

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["pagination"]["total_count"], 1)
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["items"][0]["id"], 3001)
        self.assertEqual(body["items"][0]["category_id"], "2312")

    def test_list_items_page_out_of_range(self) -> None:
        self.save_items(self.sample_items)
        resp = self.client.get("/api/market/items?page=99&limit=12", auth=self.auth)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["items"], [])
        self.assertEqual(body["pagination"]["total_count"], 2)

    # ------------------------------------------------------------------
    # GET /api/market/items/search
    # ------------------------------------------------------------------

    def test_search_items_match(self) -> None:
        self.save_items(self.sample_items)
        resp = self.client.get("/api/market/items/search?q=GSC", auth=self.auth)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["pagination"]["total_count"], 1)
        self.assertEqual(body["items"][0]["id"], 3001)

    def test_search_items_no_match(self) -> None:
        self.save_items(self.sample_items)
        resp = self.client.get("/api/market/items/search?q=不存在XYZ", auth=self.auth)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["items"], [])
        self.assertEqual(body["pagination"]["total_count"], 0)

    def test_search_items_empty_query_returns_all(self) -> None:
        self.save_items(self.sample_items)
        resp = self.client.get("/api/market/items/search?q=", auth=self.auth)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["pagination"]["total_count"], 2)

    def test_search_items_has_query_field(self) -> None:
        self.save_items(self.sample_items)
        resp = self.client.get("/api/market/items/search?q=洛琪希", auth=self.auth)
        body = resp.json()
        self.assertEqual(body["query"], "洛琪希")

    def test_search_items_filters_by_categories(self) -> None:
        self.save_items(self.sample_items)
        resp = self.client.get("/api/market/items/search?q=手办&category=2066", auth=self.auth)

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["pagination"]["total_count"], 1)
        self.assertEqual(body["items"][0]["id"], 3002)

    # ------------------------------------------------------------------
    # GET /api/market/items/{id}
    # ------------------------------------------------------------------

    def test_get_item_found(self) -> None:
        self.save_items([self.sample_items[0]])
        resp = self.client.get("/api/market/items/3001", auth=self.auth)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("item", body)
        self.assertEqual(body["item"]["id"], 3001)
        self.assertEqual(body["item"]["show_price"], "100.00")

    def test_get_item_not_found(self) -> None:
        resp = self.client.get("/api/market/items/9999", auth=self.auth)
        self.assertEqual(resp.status_code, 404)
        body = resp.json()
        self.assertIn("error", body)

    # ------------------------------------------------------------------
    # GET /api/market/items/{id}/price-history
    # ------------------------------------------------------------------

    def test_price_history_empty(self) -> None:
        self.save_items([self.sample_items[0]])
        resp = self.client.get("/api/market/items/3001/price-history", auth=self.auth)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("history", body)
        self.assertEqual(len(body["history"]), 1)  # 1 entry on first save

    def test_price_history_multiple_changes(self) -> None:
        self.save_items([self.sample_items[0]])
        updated = dict(self.sample_items[0])
        updated["price"] = 9500
        updated["showPrice"] = "95.00"
        self.save_items([updated])

        resp = self.client.get("/api/market/items/3001/price-history", auth=self.auth)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(len(body["history"]), 2)

    def test_price_history_unknown_item(self) -> None:
        resp = self.client.get("/api/market/items/9999/price-history", auth=self.auth)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["history"], [])

    # ------------------------------------------------------------------
    # Route resolution — /search must not be captured by /{id}
    # ------------------------------------------------------------------

    def test_search_route_not_captured_by_item_id_route(self) -> None:
        """Ensure /items/search is handled by the search handler, not /{item_id}."""
        resp = self.client.get("/api/market/items/search?q=test", auth=self.auth)
        # Must be 200 from the search handler, not 422 (int parse fail) or 404
        self.assertEqual(resp.status_code, 200)
        self.assertIn("items", resp.json())

    # ------------------------------------------------------------------
    # GET /api/market/items/{id}/recent-listings
    # ------------------------------------------------------------------

    def test_recent_listings(self) -> None:
        self.save_items(self.sample_items)
        # 3001 is the itemsId (or c2cItemsId if we assume 1:1 for the default save_items behavior)
        resp = self.client.get("/api/market/items/3001/recent-listings", auth=self.auth)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("listings", body)
        self.assertIsInstance(body["listings"], list)
        
        # Verify bundled items are returned correctly
        # The sample for 3001 has detailDtoList with 1 item
        listings = body["listings"]
        if len(listings) > 0:
            first = listings[0]
            self.assertIn("bundled_items", first)
            self.assertIsInstance(first["bundled_items"], list)
            if len(first["bundled_items"]) > 0:
                self.assertEqual(first["bundled_items"][0].get("img"), "https://example.com/item.png")
            
            # Check price estimations
            self.assertIn("show_est_price", first)
            self.assertIn("show_est_price", first)

    # ------------------------------------------------------------------
    # Product Endpoint APIs
    # ------------------------------------------------------------------

    def test_get_product_metadata(self) -> None:
        self.save_items(self.sample_items)
        resp = self.client.get("/api/market/product/50", auth=self.auth)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("product", body)
        self.assertEqual(body["product"]["items_id"], 50)
        self.assertEqual(body["product"]["name"], "Test Bundled Item")

    def test_get_product_metadata_not_found(self) -> None:
        resp = self.client.get("/api/market/product/99999", auth=self.auth)
        self.assertEqual(resp.status_code, 404)

    def test_product_price_history(self) -> None:
        self.save_items(self.sample_items)
        resp = self.client.get("/api/market/product/50/price-history", auth=self.auth)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["items_id"], 50)
        self.assertIsInstance(body["history"], list)

    def test_product_recent_listings(self) -> None:
        self.save_items(self.sample_items)
        resp = self.client.get("/api/market/product/50/recent-listings", auth=self.auth)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("listings", body)
        self.assertIsInstance(body["listings"], list)

if __name__ == "__main__":
    unittest.main()
