import os
import sys
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient


os.environ["BSM_DB_BACKEND"] = "sqlite"
os.environ["BSM_DB_SQLITE_URL"] = "sqlite:///:memory:"

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
SRC_ROOT = os.path.join(PROJECT_ROOT, "src")
if SRC_ROOT not in sys.path:
    sys.path.insert(0, SRC_ROOT)

from backend.main import app
from backend.auth import get_current_user


class RefreshApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        app.dependency_overrides = {}
        app.dependency_overrides[get_current_user] = lambda: {"username": "testuser"}
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides = {}

    def test_refresh_market_item(self) -> None:
        mock_item_data = {
            "code": 0,
            "message": "success",
            "data": {
                "c2cItemsId": 195670144708,
                "type": 1,
                "c2cItemsName": "ALTER 测试手办",
                "showPrice": "850",
                "price": 85000,
                "publishStatus": 2,
                "saleStatus": 1,
                "dropReason": "手动下架",
                "detailDtoList": [],
            },
        }

        with (
            patch("backend.routers.market.load_next_bili_session", return_value={"cookies": "test_cookie"}),
            patch("backend.routers.market.get_item_detail", return_value=mock_item_data),
            patch("backend.routers.market.update_item_status", return_value=None),
            patch(
                "backend.routers.market.get_market_item",
                return_value={
                    "id": 195670144708,
                    "name": "ALTER 测试手办",
                    "publish_status": 2,
                    "sale_status": 1,
                    "drop_reason": "手动下架",
                },
            ),
        ):
            response = self.client.post("/api/market/items/195670144708/refresh")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["item"]["publish_status"], 2)

    def test_batch_refresh_market_items(self) -> None:
        def mock_get_item_detail(cookies: str, item_id: int) -> dict:
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "c2cItemsId": item_id,
                    "type": 1,
                    "c2cItemsName": f"Item {item_id}",
                    "showPrice": "850",
                    "price": 85000,
                    "publishStatus": 2,
                    "saleStatus": 1,
                    "dropReason": "手动下架",
                    "detailDtoList": [],
                },
            }

        with (
            patch("backend.routers.market.load_next_bili_session", return_value={"cookies": "test_cookie"}),
            patch("backend.routers.market.get_item_detail", side_effect=mock_get_item_detail),
            patch("backend.routers.market.update_item_status", return_value=None),
        ):
            response = self.client.post("/api/market/items/batch-refresh", json={"ids": [111, 222, 333]})

            self.assertEqual(response.status_code, 200)
            results = response.json()["results"]
            self.assertEqual(len(results), 3)
            for row in results:
                self.assertTrue(row["ok"])
                self.assertEqual(row["publish_status"], 2)
                self.assertTrue(
                    {"c2c_items_id", "publish_status", "sale_status", "drop_reason", "ok"}.issubset(row.keys())
                )

            many_ids = list(range(1001, 1015))
            response = self.client.post("/api/market/items/batch-refresh", json={"ids": many_ids})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.json()["results"]), 10)

            response = self.client.post("/api/market/items/batch-refresh", json={"ids": []})
            self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
