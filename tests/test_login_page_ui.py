import os
import unittest


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read_text(relative_path: str) -> str:
    file_path = os.path.join(PROJECT_ROOT, relative_path)
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


class LoginPageUiTestCase(unittest.TestCase):
    def test_login_page_fetches_public_login_settings(self) -> None:
        content = read_text("src/frontend/src/app/page.tsx")

        self.assertIn('fetch("/api/public/login-settings"', content)
        self.assertIn("cloudflare_validation_enabled", content)
        self.assertIn("cloudflare_turnstile_site_key", content)

    def test_login_page_passes_turnstile_token_to_login(self) -> None:
        content = read_text("src/frontend/src/app/page.tsx")

        self.assertIn("const [cfToken, setCfToken] = useState(\"\");", content)
        self.assertIn("const result = await login(username.trim(), password.trim(), cfToken);", content)
        self.assertIn("请先完成 Cloudflare 验证", content)


if __name__ == "__main__":
    unittest.main()
