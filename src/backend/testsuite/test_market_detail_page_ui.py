import os
import unittest


PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)


def read_text(relative_path: str) -> str:
    file_path = os.path.join(PROJECT_ROOT, relative_path)
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


class MarketDetailPageUiTestCase(unittest.TestCase):
    def test_market_detail_page_shows_discount_text(self) -> None:
        content = read_text("src/frontend/src/app/market/[id]/page.tsx")

        self.assertIn("function discountText", content)
        self.assertIn("当前价格：<strong>¥ {item.show_price ?? \"—\"}</strong>", content)
        self.assertIn("discountText(item.show_price, item.show_market_price)", content)
        self.assertIn("discountText(listing.show_price, listing.show_market_price)", content)

    def test_market_detail_page_keeps_back_link_prefetch_enabled(self) -> None:
        content = read_text("src/frontend/src/app/market/[id]/page.tsx")

        self.assertIn('<Link href="/market" className="bsm-link" style={{ fontSize: "0.875rem" }}>', content)
        self.assertNotIn('<Link href="/market" className="bsm-link" style={{ fontSize: "0.875rem" }} prefetch={false}>', content)

    def test_market_detail_page_shows_blindbox_item_sku_in_one_line(self) -> None:
        content = read_text("src/frontend/src/app/market/[id]/page.tsx")

        self.assertIn("盲盒ID：", content)
        self.assertIn("Item ID：", content)
        self.assertIn("SKU ID：", content)
        self.assertIn('{" | "}', content)


if __name__ == "__main__":
    unittest.main()
