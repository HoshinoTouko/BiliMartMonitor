import os
import unittest


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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


if __name__ == "__main__":
    unittest.main()
