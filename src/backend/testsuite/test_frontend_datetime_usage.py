import os
import unittest


PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
FRONTEND_ROOT = os.path.join(PROJECT_ROOT, "src", "frontend", "src")


class FrontendDatetimeUsageTestCase(unittest.TestCase):
    def test_datetime_helper_exists_and_handles_epoch_paths(self) -> None:
        path = os.path.join(FRONTEND_ROOT, "lib", "datetime.ts")
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()

        self.assertIn("parseApiDate", source)
        self.assertIn("Math.abs(value) < 1e12 ? value * 1000 : value", source)
        self.assertIn("formatMonthDayTime", source)

    def test_pages_use_shared_datetime_helper(self) -> None:
        pages = [
            os.path.join(FRONTEND_ROOT, "app", "app", "page.tsx"),
            os.path.join(FRONTEND_ROOT, "app", "admin", "settings", "page.tsx"),
            os.path.join(FRONTEND_ROOT, "app", "market", "page.tsx"),
            os.path.join(FRONTEND_ROOT, "app", "market", "[id]", "page.tsx"),
            os.path.join(FRONTEND_ROOT, "app", "product", "[id]", "page.tsx"),
        ]
        for path in pages:
            with self.subTest(path=path):
                with open(path, "r", encoding="utf-8") as f:
                    source = f.read()
                self.assertIn('from "@/lib/datetime"', source)
                self.assertNotIn('replace(" ", "T")', source)

