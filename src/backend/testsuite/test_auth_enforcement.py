import os
import sys
import tempfile
import unittest
import importlib
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
SRC_ROOT = os.path.join(PROJECT_ROOT, "src")
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if SRC_ROOT not in sys.path:
    sys.path.insert(0, SRC_ROOT)

class AuthEnforcementTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.db_fd, self.db_path = tempfile.mkstemp(prefix="bsm-auth-test-", suffix=".db")
        os.close(self.db_fd)
        self.cfg_fd, self.cfg_path = tempfile.mkstemp(prefix="bsm-auth-test-", suffix=".yaml")
        os.close(self.cfg_fd)
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            f.write("")
        
        os.environ["BSM_TESTING"] = "1"
        os.environ["BSM_DB_BACKEND"] = "sqlite"
        os.environ["BSM_TEST_DB_PATH"] = self.db_path
        os.environ["BSM_CONFIG_PATH"] = self.cfg_path

        import backend.auth as auth_mod
        importlib.reload(auth_mod)
        auth_mod._FAIL2BAN_STATE.clear()
        import backend.main as main_mod
        importlib.reload(main_mod)
        from backend.main import app
        from bsm.settings import upsert_access_user
        self.client = TestClient(app)
        
        # Seed users
        upsert_access_user(username="admin", password_hash="adminpass", roles=["admin"], status="active")
        upsert_access_user(username="user", password_hash="userpass", roles=["user"], status="active")
        
        self.admin_auth = ("admin", "adminpass")
        self.user_auth = ("user", "userpass")

    def tearDown(self) -> None:
        for key in ("BSM_TESTING", "BSM_DB_BACKEND", "BSM_TEST_DB_PATH", "BSM_CONFIG_PATH"):
            os.environ.pop(key, None)
        if os.path.exists(self.db_path): os.remove(self.db_path)
        if os.path.exists(self.cfg_path): os.remove(self.cfg_path)

    def test_market_requires_auth(self) -> None:
        # No auth
        resp = self.client.get("/api/market/items")
        self.assertEqual(resp.status_code, 401)
        
        # User auth (OK)
        resp = self.client.get("/api/market/items", auth=self.user_auth)
        self.assertEqual(resp.status_code, 200)

    def test_admin_sessions_requires_admin(self) -> None:
        # No auth
        resp = self.client.get("/api/admin/sessions")
        self.assertEqual(resp.status_code, 401)
        
        # User auth (403)
        resp = self.client.get("/api/admin/sessions", auth=self.user_auth)
        self.assertEqual(resp.status_code, 403)
        
        # Admin auth (OK)
        resp = self.client.get("/api/admin/sessions", auth=self.admin_auth)
        self.assertEqual(resp.status_code, 200)

    @patch("backend.routers.qr.create_bili_login_qr")
    def test_qr_admin_requires_admin(self, mock_create_bili_login_qr) -> None:
        mock_create_bili_login_qr.return_value = {
            "login_key": "test-key",
            "login_url": "https://example.com/login",
            "qr_image": "data:image/png;base64,test",
        }
        # No auth
        resp = self.client.get("/api/admin/qr/create")
        self.assertEqual(resp.status_code, 401)
        
        # User auth (403)
        resp = self.client.get("/api/admin/qr/create", auth=self.user_auth)
        self.assertEqual(resp.status_code, 403)
        
        # Admin auth (OK)
        resp = self.client.get("/api/admin/qr/create", auth=self.admin_auth)
        self.assertEqual(resp.status_code, 200)

    def test_settings_requires_admin(self) -> None:
        resp = self.client.get("/api/settings", auth=self.user_auth)
        self.assertEqual(resp.status_code, 403)
        
        resp = self.client.get("/api/settings", auth=self.admin_auth)
        self.assertEqual(resp.status_code, 200)

    def test_user_notifications_requires_own_or_admin(self) -> None:
        # User A trying to read User B (403)
        resp = self.client.get("/api/settings/user-notifications?username=admin", auth=self.user_auth)
        self.assertEqual(resp.status_code, 403)
        
        # Admin trying to read User B (OK)
        resp = self.client.get("/api/settings/user-notifications?username=user", auth=self.admin_auth)
        self.assertEqual(resp.status_code, 200)

    def test_login_fail2ban_blocks_repeated_failures(self) -> None:
        for _ in range(4):
            resp = self.client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
            self.assertEqual(resp.status_code, 401)

        fifth = self.client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
        self.assertEqual(fifth.status_code, 429)
        self.assertIn("Too many failed attempts", fifth.json()["error"])

        blocked = self.client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
        self.assertEqual(blocked.status_code, 429)

    def test_login_fail2ban_uses_five_minute_window(self) -> None:
        import backend.auth as auth_mod

        auth_mod._FAIL2BAN_STATE.clear()
        base = 1000.0

        with patch("backend.auth.time.monotonic", side_effect=[base, base + 60, base + 120, base + 180, base + 301]):
            for _ in range(5):
                blocked = auth_mod.record_failed_auth_attempt("203.0.113.10", "admin")

        self.assertIsNone(blocked)
        with patch("backend.auth.time.monotonic", return_value=base + 301):
            self.assertIsNone(auth_mod.reject_if_banned("203.0.113.10"))

        with patch("backend.auth.time.monotonic", side_effect=[base, base + 60, base + 120, base + 180, base + 240, base + 240]):
            auth_mod._FAIL2BAN_STATE.clear()
            for _ in range(4):
                blocked = auth_mod.record_failed_auth_attempt("203.0.113.10", "admin")
                self.assertIsNone(blocked)
            blocked = auth_mod.record_failed_auth_attempt("203.0.113.10", "admin")

        self.assertIsNotNone(blocked)
        self.assertEqual(blocked.status_code, 429)
        with patch("backend.auth.time.monotonic", return_value=base + 241):
            self.assertIsNotNone(auth_mod.reject_if_banned("203.0.113.10"))

    def test_login_fail2ban_honors_forwarded_ip(self) -> None:
        for _ in range(4):
            resp = self.client.post(
                "/api/auth/login",
                headers={"X-Forwarded-For": "198.51.100.20"},
                json={"username": "admin", "password": "wrong"},
            )
            self.assertEqual(resp.status_code, 401)

        blocked = self.client.post(
            "/api/auth/login",
            headers={"X-Forwarded-For": "198.51.100.20"},
            json={"username": "admin", "password": "wrong"},
        )
        self.assertEqual(blocked.status_code, 429)

        other_ip = self.client.post(
            "/api/auth/login",
            headers={"X-Forwarded-For": "198.51.100.21"},
            json={"username": "admin", "password": "adminpass"},
        )
        self.assertEqual(other_ip.status_code, 200)

    def test_login_sets_session_cookie_and_auth_me_uses_it(self) -> None:
        login = self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "adminpass"},
        )

        self.assertEqual(login.status_code, 200)
        self.assertTrue(login.json()["ok"])
        self.assertIn("bsm_session=", login.headers.get("set-cookie", ""))

        me = self.client.get("/api/auth/me")
        self.assertEqual(me.status_code, 200)
        self.assertTrue(me.json()["ok"])
        self.assertEqual(me.json()["username"], "admin")
        self.assertEqual(me.json()["role"], "admin")

    def test_logout_clears_session_cookie(self) -> None:
        login = self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "adminpass"},
        )
        self.assertEqual(login.status_code, 200)

        logout = self.client.post("/api/auth/logout")
        self.assertEqual(logout.status_code, 200)
        self.assertIn("bsm_session=", logout.headers.get("set-cookie", ""))

        me = self.client.get("/api/auth/me")
        self.assertEqual(me.status_code, 401)

    def test_login_requires_cloudflare_token_when_enabled(self) -> None:
        response = self.client.put(
            "/api/settings",
            auth=self.admin_auth,
            json={
                "cloudflare_validation_enabled": True,
                "cloudflare_turnstile_site_key": "site-key",
                "cloudflare_turnstile_secret_key": "secret-key",
            },
        )
        self.assertEqual(response.status_code, 200)

        blocked = self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "adminpass"},
        )
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(blocked.json()["error"], "Cloudflare verification is required")

    def test_login_rejects_empty_cloudflare_token_when_enabled(self) -> None:
        response = self.client.put(
            "/api/settings",
            auth=self.admin_auth,
            json={
                "cloudflare_validation_enabled": True,
                "cloudflare_turnstile_site_key": "site-key",
                "cloudflare_turnstile_secret_key": "secret-key",
            },
        )
        self.assertEqual(response.status_code, 200)

        blocked = self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "adminpass", "cf_token": ""},
        )
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(blocked.json()["error"], "Cloudflare verification is required")

    @patch("requests.post")
    def test_login_rejects_invalid_cloudflare_token_when_enabled(self, mock_requests_post) -> None:
        response = self.client.put(
            "/api/settings",
            auth=self.admin_auth,
            json={
                "cloudflare_validation_enabled": True,
                "cloudflare_turnstile_site_key": "site-key",
                "cloudflare_turnstile_secret_key": "secret-key",
            },
        )
        self.assertEqual(response.status_code, 200)

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"success": False}
        mock_requests_post.return_value = mock_resp

        blocked = self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "adminpass", "cf_token": "fake-token"},
        )
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(blocked.json()["error"], "Cloudflare verification failed")

    @patch("backend.routers.auth.verify_cloudflare_token")
    def test_login_accepts_cloudflare_token_when_verification_passes(self, mock_verify_cloudflare_token) -> None:
        response = self.client.put(
            "/api/settings",
            auth=self.admin_auth,
            json={
                "cloudflare_validation_enabled": True,
                "cloudflare_turnstile_site_key": "site-key",
                "cloudflare_turnstile_secret_key": "secret-key",
            },
        )
        self.assertEqual(response.status_code, 200)
        mock_verify_cloudflare_token.return_value = (True, "")

        success = self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "adminpass", "cf_token": "token-ok"},
        )
        self.assertEqual(success.status_code, 200)
        self.assertTrue(success.json()["ok"])

    def test_default_bootstrap_admin_is_admin_admin(self) -> None:
        second_fd, second_db_path = tempfile.mkstemp(prefix="bsm-auth-default-", suffix=".db")
        os.close(second_fd)
        second_cfg_fd, second_cfg_path = tempfile.mkstemp(prefix="bsm-auth-default-", suffix=".yaml")
        os.close(second_cfg_fd)
        with open(second_cfg_path, "w", encoding="utf-8") as f:
            f.write("")

        old_db_path = os.environ["BSM_TEST_DB_PATH"]
        old_cfg_path = os.environ["BSM_CONFIG_PATH"]
        try:
            os.environ["BSM_TEST_DB_PATH"] = second_db_path
            os.environ["BSM_CONFIG_PATH"] = second_cfg_path

            import backend.auth as auth_mod
            importlib.reload(auth_mod)
            auth_mod._FAIL2BAN_STATE.clear()
            auth_mod._DEFAULT_ACCESS_USERS_ENSURED = False

            user = auth_mod.authenticate_access_user("admin", "admin")
            self.assertIsNotNone(user)
            self.assertEqual(user["username"], "admin")
            self.assertEqual(user["role"], "admin")
        finally:
            os.environ["BSM_TEST_DB_PATH"] = old_db_path
            os.environ["BSM_CONFIG_PATH"] = old_cfg_path
            if os.path.exists(second_db_path):
                os.remove(second_db_path)
            if os.path.exists(second_cfg_path):
                os.remove(second_cfg_path)
            import backend.auth as auth_mod
            importlib.reload(auth_mod)

if __name__ == "__main__":
    unittest.main()
