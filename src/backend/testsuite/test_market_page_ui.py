import os
import unittest


PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)


def read_text(relative_path: str) -> str:
    file_path = os.path.join(PROJECT_ROOT, relative_path)
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


class MarketPageUiTestCase(unittest.TestCase):
    def test_market_page_exposes_multi_category_filter(self) -> None:
        content = read_text("src/frontend/src/app/market/page.tsx")

        self.assertIn('params.set("category", categories.join(","));', content)
        self.assertIn('{ id: "2312", label: "手办" }', content)
        self.assertIn('{ id: "2066", label: "模型" }', content)
        self.assertIn('type="checkbox"', content)
        self.assertIn("setCategoryFilters", content)
        self.assertIn("setCategoryDraftFilters", content)
        self.assertIn('if (openFilter === "category")', content)
        self.assertIn('className={`bsm-market-filter-trigger ${openFilter === "category" ? "open" : ""}`}', content)
        self.assertIn('className="bsm-market-filter-menu"', content)
        self.assertIn('className="bsm-market-filter-check-box"', content)
        self.assertNotIn("<select", content)

    def test_market_page_shows_discount_text(self) -> None:
        content = read_text("src/frontend/src/app/market/page.tsx")

        self.assertIn("function discountText", content)
        self.assertIn("show_market_price", content)
        self.assertIn("toFixed(1)}折", content)
        self.assertIn('{ value: "TIME_DESC", label: "创建时间(新-旧)" }', content)
        self.assertIn('{ value: "ID_DESC", label: "ID排序(大-小)" }', content)
        self.assertIn('{ value: "ID_ASC", label: "ID排序(小-大)" }', content)

    def test_market_page_disables_link_prefetch(self) -> None:
        content = read_text("src/frontend/src/app/market/page.tsx")

        self.assertIn("className=\"bsm-market-card\"", content)
        self.assertIn("prefetch={false}", content)


if __name__ == "__main__":
    unittest.main()
