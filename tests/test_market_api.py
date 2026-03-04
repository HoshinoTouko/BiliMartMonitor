import os
import sys
import tempfile
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_ROOT = os.path.join(PROJECT_ROOT, "src")
if SRC_ROOT not in sys.path:
    sys.path.insert(0, SRC_ROOT)

from bsm import db


SAMPLE_ITEMS = [
    {
        "c2cItemsId": 2001,
        "type": 1,
        "c2cItemsName": "洛琪希 手办 GSC 1/7",
        "totalItemsCount": 1,
        "price": 10000,
        "showPrice": "100.00",
        "showMarketPrice": "130.00",
        "uid": "u1",
        "paymentTime": 1,
        "isMyPublish": False,
        "uface": "https://example.com/face1.jpg",
        "uname": "alice",
        "detailDtoList": [{"img": "https://example.com/item1.png"}],
    },
    {
        "c2cItemsId": 2002,
        "type": 1,
        "c2cItemsName": "灰原哀 手办 ALTER",
        "totalItemsCount": 1,
        "price": 28000,
        "showPrice": "280.00",
        "showMarketPrice": "350.00",
        "uid": "u2",
        "paymentTime": 2,
        "isMyPublish": False,
        "uface": "https://example.com/face2.jpg",
        "uname": "bob",
        "detailDtoList": [{"imgUrl": "https://example.com/item2.png"}],
    },
    {
        "c2cItemsId": 2003,
        "type": 1,
        "c2cItemsName": "艾莉丝 手办 KotobuKiya",
        "totalItemsCount": 1,
        "price": 8500,
        "showPrice": "85.00",
        "showMarketPrice": "100.00",
        "uid": "u3",
        "paymentTime": 3,
        "isMyPublish": False,
        "uface": "",
        "uname": "carol",
        "detailDtoList": [],
    },
]


class MarketAPITestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.db_fd, self.db_path = tempfile.mkstemp(prefix="bsm-market-test-", suffix=".db")
        os.close(self.db_fd)
        self.env_fd, self.env_path = tempfile.mkstemp(prefix="bsm-env-", suffix=".env")
        os.close(self.env_fd)
        os.environ["BSM_TESTING"] = "1"
        os.environ["BSM_DB_BACKEND"] = "sqlite"
        os.environ["BSM_TEST_DB_PATH"] = self.db_path
        os.environ["BSM_ENV_PATH"] = self.env_path

    def tearDown(self) -> None:
        for key in ("BSM_TESTING", "BSM_DB_BACKEND", "BSM_TEST_DB_PATH", "BSM_DB_PATH", "BSM_ENV_PATH"):
            os.environ.pop(key, None)
        for path in (self.db_path, self.env_path):
            if os.path.exists(path):
                os.remove(path)

    # ------------------------------------------------------------------
    # list_market_items
    # ------------------------------------------------------------------

    def test_list_market_items_empty(self) -> None:
        items, total_count, total_pages = db.list_market_items()
        self.assertEqual(items, [])
        self.assertEqual(total_count, 0)
        self.assertEqual(total_pages, 0)

    def test_list_market_items_returns_items(self) -> None:
        db.save_items(SAMPLE_ITEMS)
        items, total_count, total_pages = db.list_market_items(page=1, limit=12)
        self.assertEqual(total_count, 3)
        self.assertEqual(len(items), 3)

    def test_list_market_items_pagination(self) -> None:
        db.save_items(SAMPLE_ITEMS)
        items_p1, total, pages = db.list_market_items(page=1, limit=2)
        self.assertEqual(len(items_p1), 2)
        self.assertEqual(total, 3)
        self.assertEqual(pages, 2)

        items_p2, _, _ = db.list_market_items(page=2, limit=2)
        self.assertEqual(len(items_p2), 1)

        # No overlap between pages
        ids_p1 = {it["id"] for it in items_p1}
        ids_p2 = {it["id"] for it in items_p2}
        self.assertEqual(ids_p1 & ids_p2, set())

    def test_list_market_items_total_pages_calculation(self) -> None:
        db.save_items(SAMPLE_ITEMS)
        _, total_count, total_pages = db.list_market_items(page=1, limit=12)
        self.assertEqual(total_count, 3)
        self.assertEqual(total_pages, 1)  # 3 items fit in 1 page of 12

        _, _, pages_of_2 = db.list_market_items(page=1, limit=2)
        self.assertEqual(pages_of_2, 2)  # ceil(3/2) = 2

    def test_list_market_items_img_url_extracted(self) -> None:
        db.save_items(SAMPLE_ITEMS)
        items, _, _ = db.list_market_items()
        by_id = {it["id"]: it for it in items}
        self.assertEqual(by_id[2001]["img_url"], "https://example.com/item1.png")
        self.assertEqual(by_id[2002]["img_url"], "https://example.com/item2.png")
        self.assertEqual(by_id[2003]["img_url"], "")  # no detail

    # ------------------------------------------------------------------
    # search_market_items
    # ------------------------------------------------------------------

    def test_search_market_items_empty_keyword(self) -> None:
        db.save_items(SAMPLE_ITEMS)
        items, total_count, _ = db.search_market_items(keyword="")
        # empty keyword → LIKE %% → matches all
        self.assertEqual(total_count, 3)
        self.assertEqual(len(items), 3)

    def test_search_market_items_by_keyword(self) -> None:
        db.save_items(SAMPLE_ITEMS)
        items, total_count, _ = db.search_market_items(keyword="手办")
        self.assertEqual(total_count, 3)

        items2, total2, _ = db.search_market_items(keyword="GSC")
        self.assertEqual(total2, 1)
        self.assertEqual(items2[0]["id"], 2001)

    def test_search_market_items_no_match(self) -> None:
        db.save_items(SAMPLE_ITEMS)
        items, total, pages = db.search_market_items(keyword="不存在的关键词XYZ")
        self.assertEqual(total, 0)
        self.assertEqual(items, [])
        self.assertEqual(pages, 0)

    def test_search_market_items_pagination(self) -> None:
        db.save_items(SAMPLE_ITEMS)
        items, total, pages = db.search_market_items(keyword="手办", page=1, limit=2)
        self.assertEqual(total, 3)
        self.assertEqual(pages, 2)
        self.assertEqual(len(items), 2)

    # ------------------------------------------------------------------
    # price history
    # ------------------------------------------------------------------

    def test_price_history_recorded_on_new_item(self) -> None:
        db.save_items([SAMPLE_ITEMS[0]])
        history = db.get_item_price_history(2001)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["price"], 10000)
        self.assertEqual(history[0]["show_price"], "100.00")

    def test_price_history_recorded_on_price_change(self) -> None:
        db.save_items([SAMPLE_ITEMS[0]])
        # Same item, different price
        updated = dict(SAMPLE_ITEMS[0])
        updated["price"] = 9500
        updated["showPrice"] = "95.00"
        db.save_items([updated])
        history = db.get_item_price_history(2001)
        self.assertEqual(len(history), 2, "Should record initial + changed price")
        prices = [h["price"] for h in history]
        self.assertIn(10000, prices)
        self.assertIn(9500, prices)

    def test_price_history_no_duplicate_on_same_price(self) -> None:
        db.save_items([SAMPLE_ITEMS[0]])
        db.save_items([SAMPLE_ITEMS[0]])  # same price again
        history = db.get_item_price_history(2001)
        self.assertEqual(len(history), 1, "Should not duplicate history for same price")

    def test_price_history_ordered_ascending(self) -> None:
        db.save_items([SAMPLE_ITEMS[0]])
        updated = dict(SAMPLE_ITEMS[0])
        updated["price"] = 9500
        updated["showPrice"] = "95.00"
        db.save_items([updated])
        history = db.get_item_price_history(2001)
        self.assertEqual(len(history), 2)
        # First entry is oldest (ASC order)
        self.assertEqual(history[0]["price"], 10000)
        self.assertEqual(history[1]["price"], 9500)

    def test_price_history_empty_for_unknown_item(self) -> None:
        history = db.get_item_price_history(9999)
        self.assertEqual(history, [])

    # ------------------------------------------------------------------
    # get_market_item
    # ------------------------------------------------------------------

    def test_get_market_item_found(self) -> None:
        db.save_items([SAMPLE_ITEMS[1]])
        item = db.get_market_item(2002)
        self.assertIsNotNone(item)
        self.assertEqual(item["id"], 2002)
        self.assertEqual(item["name"], "灰原哀 手办 ALTER")
        self.assertEqual(item["show_price"], "280.00")
        self.assertEqual(item["img_url"], "https://example.com/item2.png")

    def test_get_market_item_not_found(self) -> None:
        item = db.get_market_item(9999)
        self.assertIsNone(item)


if __name__ == "__main__":
    unittest.main()
