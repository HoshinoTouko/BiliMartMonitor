import os
import unittest


PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)


def read_text(relative_path: str) -> str:
    file_path = os.path.join(PROJECT_ROOT, relative_path)
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


class DashboardUiTestCase(unittest.TestCase):
    def test_user_dashboard_has_refresh_action(self) -> None:
        content = read_text("src/frontend/src/app/app/page.tsx")

        self.assertIn("刷新首页数据", content)
        self.assertIn("await Promise.all([loadDashboard(), runDbPing()]);", content)
        self.assertIn('className="bsm-btn bsm-btn-outline"', content)

    def test_admin_settings_exposes_cur_mode_copy(self) -> None:
        content = read_text("src/frontend/src/app/admin/settings/page.tsx")

        self.assertIn('value="continue_until_repeat"', content)
        self.assertIn("CUR（遇重复回首页，最多 50 页）", content)
        self.assertIn("重启 Cron", content)
        self.assertIn("立即扫描", content)
        self.assertIn('apiPost("/api/settings/cron/restart"', content)
        self.assertIn('apiPost("/api/settings/cron/trigger"', content)
        self.assertIn("扫描任务已重启并立即执行", content)
        self.assertIn("Cron 已重启并立即执行", content)
        self.assertIn("if (loading || !settings)", content)
        self.assertIn('apiGet("/api/settings/logs?n=50")', content)
        self.assertIn("创建时间排序（TIME_DESC，默认）", content)

    def test_footer_uses_shared_version_and_copyright(self) -> None:
        footer = read_text("src/frontend/src/components/AppFooter.tsx")
        info = read_text("src/frontend/src/lib/appInfo.ts")

        self.assertIn('export const APP_VERSION = "0.9.0"', info)
        self.assertIn('export const APP_COPYRIGHT = "© Touko Hoshino"', info)
        self.assertIn("v{APP_VERSION} | {APP_COPYRIGHT}", footer)


if __name__ == "__main__":
    unittest.main()
