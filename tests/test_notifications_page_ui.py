import os
import unittest


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read_text(relative_path: str) -> str:
    file_path = os.path.join(PROJECT_ROOT, relative_path)
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


class NotificationsPageUiTestCase(unittest.TestCase):
    def test_manual_refresh_polls_for_telegram_ids_with_one_second_interval(self) -> None:
        content = read_text("src/frontend/src/app/notifications/page.tsx")

        self.assertIn("for (let attempt = 0; attempt < 6; attempt += 1)", content)
        self.assertIn("window.setTimeout(resolve, 1000);", content)
        self.assertIn("setTelegramIdsText(latestIds);", content)
        self.assertIn('setTestMsg(latestIds !== previousIds ? "✅ 已同步 Telegram 绑定状态" : "✅ 已触发机器人刷新");', content)

    def test_test_push_hint_has_been_removed(self) -> None:
        content = read_text("src/frontend/src/app/notifications/page.tsx")

        self.assertNotIn("向当前填写的 Telegram ID 推送一条包含当前时间的测试消息", content)

    def test_telegram_binding_and_test_push_are_separate_sections(self) -> None:
        content = read_text("src/frontend/src/app/notifications/page.tsx")

        self.assertIn('<label className="bsm-settings-label">Telegram 绑定</label>', content)
        self.assertIn('<label className="bsm-settings-label">测试推送</label>', content)
        self.assertNotIn('className="bsm-notification-telegram-layout"', content)


if __name__ == "__main__":
    unittest.main()
