import os
import sys
import tempfile
import unittest
import importlib

from fastapi.testclient import TestClient

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_ROOT = os.path.join(PROJECT_ROOT, "src")
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if SRC_ROOT not in sys.path:
    sys.path.insert(0, SRC_ROOT)


class AccountsRouterTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.db_fd, self.db_path = tempfile.mkstemp(prefix="bsm-accounts-router-", suffix=".db")
        os.close(self.db_fd)
        self.cfg_fd, self.cfg_path = tempfile.mkstemp(prefix="bsm-accounts-router-", suffix=".yaml")
        os.close(self.cfg_fd)
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            f.write("")
        os.environ["BSM_TESTING"] = "1"
        os.environ["BSM_DB_BACKEND"] = "sqlite"
        os.environ["BSM_TEST_DB_PATH"] = self.db_path
        os.environ["BSM_CONFIG_PATH"] = self.cfg_path
        import bsm.db as db_mod
        importlib.reload(db_mod)
        import bsm.settings as settings_mod
        importlib.reload(settings_mod)
        import backend.auth as auth_mod
        importlib.reload(auth_mod)
        import bsm.telegrambot as telegrambot_mod
        importlib.reload(telegrambot_mod)
        import backend.main as main_mod
        importlib.reload(main_mod)
        from backend.main import app
        from bsm.settings import upsert_access_user

        self.client = TestClient(app)
        self.admin_headers = {"Authorization": "Basic dGVzdGFkbWluOmFkbWlu"}
        self.user_headers = {"Authorization": "Basic ZGVtbzp1c2VyMTIzNA=="}
        upsert_access_user(
            username="testadmin",
            display_name="Test Admin",
            password_hash="admin",
            roles=["admin"],
            status="active",
        )
        upsert_access_user(
            username="demo",
            display_name="Demo User",
            password_hash="user1234",
            roles=["user"],
            status="active",
        )

    def tearDown(self) -> None:
        for key in ("BSM_TESTING", "BSM_DB_BACKEND", "BSM_TEST_DB_PATH", "BSM_CONFIG_PATH"):
            os.environ.pop(key, None)
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        if os.path.exists(self.cfg_path):
            os.remove(self.cfg_path)

    def test_get_current_account(self) -> None:
        response = self.client.get("/api/account/me", headers=self.admin_headers)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["account"]["username"], "testadmin")
        self.assertEqual(data["account"]["role"], "admin")

    def test_get_account_dashboard(self) -> None:
        response = self.client.get("/api/account/dashboard", headers=self.admin_headers)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["today_refresh_count"], 0)
        self.assertEqual(data["today_new_item_count"], 0)
        self.assertEqual(data["user_count"], 2)
        self.assertEqual(data["active_session_count"], 0)
        self.assertEqual(data["item_count"], 0)
        self.assertIsNone(data["last_scan_at"])

    def test_account_db_ping_success(self) -> None:
        response = self.client.get("/api/account/db-ping", headers=self.user_headers)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("latency_ms", data)
        self.assertIsNone(data["error"])

    def test_change_my_password(self) -> None:
        response = self.client.put(
            "/api/account/me/password",
            headers=self.admin_headers,
            json={"current_password": "admin", "new_password": "admin2"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

        relogin = self.client.post(
            "/api/auth/login",
            json={"username": "testadmin", "password": "admin2"},
        )
        self.assertEqual(relogin.status_code, 200)
        self.assertTrue(relogin.json()["ok"])

    def test_admin_can_create_and_list_accounts(self) -> None:
        create = self.client.post(
            "/api/account/users",
            headers=self.admin_headers,
            json={
                "username": "demo",
                "display_name": "Demo User",
                "password": "user1234",
                "roles": ["user"],
                "status": "active",
            },
        )

        self.assertEqual(create.status_code, 409)
        self.assertEqual(create.json()["error"], "username already exists")

        listed = self.client.get("/api/account/users", headers=self.admin_headers)
        self.assertEqual(listed.status_code, 200)
        usernames = [row["username"] for row in listed.json()["users"]]
        self.assertIn("testadmin", usernames)
        self.assertIn("demo", usernames)
        self.assertEqual(usernames[:2], ["demo", "testadmin"])

    def test_regular_user_can_read_own_account_only(self) -> None:
        response = self.client.get("/api/account/me", headers=self.user_headers)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["account"]["username"], "demo")
        self.assertEqual(data["account"]["role"], "user")

    def test_regular_user_cannot_list_accounts(self) -> None:
        response = self.client.get("/api/account/users", auth=("demo", "user1234"))

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "Admin privileges required")

    def test_regular_user_cannot_create_accounts(self) -> None:
        response = self.client.post(
            "/api/account/users",
            headers=self.user_headers,
            json={
                "username": "evil",
                "display_name": "Evil User",
                "password": "evil1234",
                "roles": ["admin"],
                "status": "active",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "Admin privileges required")

    def test_regular_user_cannot_delete_other_accounts(self) -> None:
        response = self.client.delete("/api/account/users/testadmin", headers=self.user_headers)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "Admin privileges required")

    def test_upsert_user_empty_password(self) -> None:
        """Verify that an admin can create/modify a user with an empty password string."""
        payload = {
            "username": "new_user_empty",
            "display_name": "New User Empty",
            "password": "",
            "roles": ["user"],
            "status": "active"
        }
        # Creation (POST)
        response = self.client.post("/api/account/users", headers=self.admin_headers, json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        
        # Modification (PUT) with different display name, keeping password empty (no change)
        payload["display_name"] = "Updated Name"
        payload["password"] = "" 
        response = self.client.put("/api/account/users/new_user_empty", headers=self.admin_headers, json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(response.json()["user"]["display_name"], "Updated Name")

    def test_rename_user(self) -> None:
        """Verify that an admin can rename a user via PUT."""
        # Create user
        self.client.post("/api/account/users", headers=self.admin_headers, json={
            "username": "oldname",
            "password": "pass",
            "roles": ["user"]
        })
        
        # Rename user
        response = self.client.put("/api/account/users/oldname", headers=self.admin_headers, json={
            "username": "newname",
            "display_name": "Renamed",
            "roles": ["user"]
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(response.json()["user"]["username"], "newname")
        
        # Verify old name is gone and new name exists
        listed = self.client.get("/api/account/users", headers=self.admin_headers)
        usernames = [u["username"] for u in listed.json()["users"]]
        self.assertIn("newname", usernames)
        self.assertNotIn("oldname", usernames)

    def test_generate_bind_code_is_valid_for_ten_minutes(self) -> None:
        from bsm.telegrambot import PENDING_BINDS, PENDING_BIND_TTL_SECONDS

        response = self.client.post("/api/account/telegram/bind-code", headers=self.user_headers)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(len(data["code"]), 6)

        code, expiry = PENDING_BINDS["demo"]
        self.assertEqual(code, data["code"])
        self.assertEqual(PENDING_BIND_TTL_SECONDS, 600)
        remaining = expiry - __import__("time").time()
        self.assertGreater(remaining, 590)
        self.assertLessEqual(remaining, 600)


if __name__ == "__main__":
    unittest.main()
