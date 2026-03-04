import os
import unittest


PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)


def read_text(relative_path: str) -> str:
    file_path = os.path.join(PROJECT_ROOT, relative_path)
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


class AccountPageUiTestCase(unittest.TestCase):
    def test_account_page_renders_my_account_before_admin_panel(self) -> None:
        content = read_text("src/frontend/src/app/account/page.tsx")

        self.assertIn('<Shell title="我的账户">', content)
        self.assertIn('<div className="bsm-section-title">当前账户</div>', content)
        self.assertIn("<AccountManagementPanel />", content)
        self.assertLess(content.index("当前账户"), content.index("<AccountManagementPanel />"))

    def test_account_management_panel_is_hidden_for_non_admin(self) -> None:
        content = read_text("src/frontend/src/components/AccountManagementPanel.tsx")

        self.assertIn('if (role !== "admin") {', content)
        self.assertIn("return null;", content)

    def test_shell_admin_nav_no_longer_has_standalone_account_management(self) -> None:
        content = read_text("src/frontend/src/components/Shell.tsx")

        self.assertIn('{ label: "Bili会话管理", href: "/admin/sessions" },', content)
        self.assertIn('{ label: "系统设置", href: "/admin/settings" },', content)
        self.assertNotIn('{ label: "账户管理", href: "/admin/users" },', content)

    def test_admin_users_page_redirects_to_account(self) -> None:
        content = read_text("src/frontend/src/app/admin/users/page.tsx")

        self.assertIn('redirect("/account");', content)


if __name__ == "__main__":
    unittest.main()
