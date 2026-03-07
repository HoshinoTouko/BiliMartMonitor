import os
import sys
import tempfile
import unittest
import importlib
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
SRC_ROOT = os.path.join(PROJECT_ROOT, "src")
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if SRC_ROOT not in sys.path:
    sys.path.insert(0, SRC_ROOT)

class SettingsRouterTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.db_fd, self.db_path = tempfile.mkstemp(prefix="bsm-settings-router-", suffix=".db")
        os.close(self.db_fd)
        self.cfg_fd, self.cfg_path = tempfile.mkstemp(prefix="bsm-settings-router-", suffix=".yaml")
        os.close(self.cfg_fd)
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            f.write("telegram:\n  bot_id: '@TestJumpBot'\n")
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
        import backend.main as main_mod
        importlib.reload(main_mod)
        from backend.main import app
        from bsm.settings import upsert_access_user
        self.client = TestClient(app)
        self.auth_headers = {"Authorization": "Basic dGVzdGFkbWluOmFkbWlu"}
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

    @patch("bsm.db.ping_database")
    def test_db_ping_success(self, mock_ping_database: MagicMock) -> None:
        response = self.client.get("/api/settings/db-ping", auth=("testadmin", "admin"))
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("latency_ms", data)
        self.assertIsNotNone(data["latency_ms"])
        self.assertIsNone(data["error"])
        mock_ping_database.assert_called_once_with()

    @patch("bsm.db.ping_database")
    def test_db_ping_error(self, mock_ping_database: MagicMock) -> None:
        mock_ping_database.side_effect = Exception("DB Connection Failed")
        response = self.client.get("/api/settings/db-ping", auth=("testadmin", "admin"))
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsNone(data["latency_ms"])
        self.assertEqual(data["error"], "DB Connection Failed")
        mock_ping_database.assert_called_once_with()

    @patch("bsm.db.get_database_size_report")
    def test_db_size_diagnostics_success(self, mock_get_database_size_report: MagicMock) -> None:
        mock_get_database_size_report.return_value = {
            "generated_at": "2026-03-07T10:00:00Z",
            "backend": "sqlite",
            "dialect": "sqlite",
            "days_window": 7,
            "table_count": 3,
            "total_rows": 120,
            "recent_total_rows": 18,
            "total_db_bytes": 1024,
            "used_db_bytes": 768,
            "free_db_bytes": 256,
            "wal_bytes": 0,
            "tables_total_bytes": 640,
            "tables": [{"name": "c2c_items", "row_count": 100, "recent_rows": 16, "table_bytes": 500, "index_bytes": 120, "total_bytes": 620}],
        }
        response = self.client.get("/api/settings/db-size?days=14&top_n=10", auth=("testadmin", "admin"))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["dialect"], "sqlite")
        self.assertEqual(data["days_window"], 7)
        self.assertEqual(len(data["tables"]), 1)
        mock_get_database_size_report.assert_called_once_with(days=14, top_n=10)

    @patch("bsm.db.get_database_size_report")
    def test_db_size_diagnostics_error(self, mock_get_database_size_report: MagicMock) -> None:
        mock_get_database_size_report.side_effect = RuntimeError("diagnostics unavailable")
        response = self.client.get("/api/settings/db-size", auth=("testadmin", "admin"))

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"], "diagnostics unavailable")
        mock_get_database_size_report.assert_called_once_with(days=7, top_n=20)

    def test_db_size_diagnostics_rejects_invalid_params(self) -> None:
        response = self.client.get("/api/settings/db-size?days=0", auth=("testadmin", "admin"))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"], "days must be between 1 and 3650")

        response = self.client.get("/api/settings/db-size?top_n=0", auth=("testadmin", "admin"))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"], "top_n must be between 1 and 200")

    @patch("bsm.db.prune_orphan_old_market_data")
    def test_db_prune_orphans_success(self, mock_prune_orphan_old_market_data: MagicMock) -> None:
        mock_prune_orphan_old_market_data.return_value = {
            "ok": True,
            "dialect": "sqlite",
            "batch_size": 2000,
            "scanned_items": 2000,
            "success_count": 1898,
            "skipped_count": 102,
            "created_products": 2210,
            "created_snapshots": 5140,
        }
        response = self.client.post("/api/settings/db-prune-orphans", auth=("testadmin", "admin"))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["success_count"], 1898)
        self.assertEqual(data["created_snapshots"], 5140)
        mock_prune_orphan_old_market_data.assert_called_once_with()

    @patch("backend.routers.settings.threading.Thread")
    def test_db_prune_orphans_start_success(self, mock_thread: MagicMock) -> None:
        thread_instance = MagicMock()
        mock_thread.return_value = thread_instance

        response = self.client.post("/api/settings/db-prune-orphans/start", auth=("testadmin", "admin"))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertIn("job_id", data)
        mock_thread.assert_called_once()
        thread_instance.start.assert_called_once_with()

    def test_db_prune_orphans_status_success(self) -> None:
        response = self.client.get("/api/settings/db-prune-orphans/status", auth=("testadmin", "admin"))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("is_running", data)
        self.assertIn("progress_percent", data)

    def test_update_settings_accepts_continue_until_repeat_scan_mode(self) -> None:
        response = self.client.put(
            "/api/settings",
            auth=("testadmin", "admin"),
            json={"scan_mode": "continue_until_repeat"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["updated"]["scan_mode"], "continue_until_repeat")
        self.assertFalse(data["restarted_cron"])

    @patch("backend.main.restart_cron_task")
    def test_update_settings_restarts_cron_when_interval_changes(self, mock_restart_cron_task: MagicMock) -> None:
        response = self.client.put(
            "/api/settings",
            auth=("testadmin", "admin"),
            json={"interval": 45},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["updated"]["interval"], 45)
        self.assertTrue(data["restarted_cron"])
        mock_restart_cron_task.assert_awaited_once_with()

    @patch("backend.cron_runner.request_scan_now")
    def test_trigger_scan_success(self, mock_request_scan_now: MagicMock) -> None:
        mock_request_scan_now.return_value = True

        response = self.client.post("/api/settings/cron/trigger", auth=("testadmin", "admin"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        mock_request_scan_now.assert_called_once_with()

    @patch("backend.cron_runner.request_scan_now")
    def test_trigger_scan_when_cron_not_running(self, mock_request_scan_now: MagicMock) -> None:
        mock_request_scan_now.return_value = False

        response = self.client.post("/api/settings/cron/trigger", auth=("testadmin", "admin"))

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"], "cron is not running")
        mock_request_scan_now.assert_called_once_with()

    @patch("backend.main.restart_cron_task")
    def test_restart_cron_success(self, mock_restart_cron_task: MagicMock) -> None:
        response = self.client.post("/api/settings/cron/restart", auth=("testadmin", "admin"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        mock_restart_cron_task.assert_awaited_once_with()

    @patch("backend.main.asyncio.create_task")
    @patch("backend.main._stop_cron_task_locked")
    @patch("backend.main.cron_loop", new_callable=MagicMock)
    def test_restart_cron_keeps_scan_progress(
        self,
        mock_cron_loop: MagicMock,
        mock_stop_cron_task_locked: MagicMock,
        mock_create_task: MagicMock,
    ) -> None:
        from backend import cron_runner
        from backend.main import restart_cron_task

        cron_runner._SCAN_CATEGORY_INDEX = 1
        cron_runner._CATEGORY_SCAN_STATE["2312"] = {"next_id": "cursor-9", "page_count": 9}

        import asyncio
        asyncio.run(restart_cron_task())

        self.assertEqual(cron_runner._SCAN_CATEGORY_INDEX, 1)
        self.assertEqual(cron_runner._CATEGORY_SCAN_STATE, {"2312": {"next_id": "cursor-9", "page_count": 9}})
        mock_stop_cron_task_locked.assert_awaited_once_with()
        mock_cron_loop.assert_called_once_with()
        mock_create_task.assert_called_once()

    def test_get_user_notifications_not_found(self) -> None:
        response = self.client.get("/api/settings/user-notifications?username=missing", auth=("testadmin", "admin"))

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"], "user not found")

    def test_get_user_notifications_success(self) -> None:
        response = self.client.get("/api/settings/user-notifications?username=testadmin", auth=("testadmin", "admin"))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["username"], "testadmin")
        # Check actual values from setUp seed
        self.assertEqual(data["keywords"], [])
        self.assertEqual(data["telegram_ids"], [])
        self.assertEqual(data["bot_id"], "@TestJumpBot")

    def test_update_user_notifications_success(self) -> None:
        response = self.client.put(
            "/api/settings/user-notifications",
            auth=("testadmin", "admin"),
            json={
                "username": "testadmin",
                "notify_enabled": False,
                "keywords": ["洛琪希", "艾莉丝"],
                "telegram_ids": ["10001", "10002"],
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        user = data["user"]
        self.assertEqual(user["username"], "testadmin")
        self.assertFalse(user["notify_enabled"])
        self.assertEqual(user["keywords"], ["洛琪希", "艾莉丝"])
        self.assertEqual(user["telegram_ids"], ["10001", "10002"])

    @patch("bsm.telegrambot.TelegramBot.send_text_to")
    @patch("bsm.settings.load_runtime_config")
    def test_user_notification_test_success(
        self,
        mock_load_runtime_config: MagicMock,
        mock_send_text_to: MagicMock,
    ) -> None:
        # Seed a more complete user for this test
        from bsm.settings import upsert_access_user
        upsert_access_user(
            username="testadmin",
            display_name="Test Admin",
            password_hash="admin",
            roles=["admin"],
            telegram_ids=["10001", "10002"],
            keywords=["洛琪希", "艾莉丝"],
            status="active"
        )
        # Remove return_value setting for the removed mock
        mock_load_runtime_config.return_value = {"telegram": {"enabled": True, "bot_token": "TEST_TOKEN"}}
        mock_send_text_to.return_value = True

        response = self.client.post(
            "/api/settings/user-notifications/test",
            auth=("testadmin", "admin"),
            json={"username": "testadmin"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["sent"], 2)
        self.assertEqual(data["failed_chat_ids"], [])
        self.assertEqual(mock_send_text_to.call_count, 2)
        sent_text = mock_send_text_to.call_args.args[1]
        self.assertIn("当前时间:", sent_text)
        self.assertIn("时区: Asia/Shanghai", sent_text)
        self.assertIn("当前关键词:", sent_text)

    @patch("bsm.settings.load_runtime_config")
    @patch("bsm.telegrambot.TelegramBot.send_text_to")
    def test_user_notification_test_allows_empty_keywords(
        self,
        mock_send_text_to: MagicMock,
        mock_load_runtime_config: MagicMock,
    ) -> None:
        # Ensure user has no keywords in DB, but a Telegram target exists
        from bsm.settings import upsert_access_user
        upsert_access_user(username="testadmin", password_hash="admin", keywords=[], telegram_ids=["10001"], status="active")
        mock_load_runtime_config.return_value = {"telegram": {"enabled": True, "bot_token": "TEST_TOKEN"}}
        mock_send_text_to.return_value = True

        response = self.client.post(
            "/api/settings/user-notifications/test",
            auth=("testadmin", "admin"),
            json={"username": "testadmin"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["sent"], 1)
        sent_text = mock_send_text_to.call_args.args[1]
        self.assertIn("当前时间:", sent_text)
        self.assertIn("时区: Asia/Shanghai", sent_text)
        self.assertNotIn("当前关键词:", sent_text)

    @patch("bsm.settings.load_runtime_config")
    def test_user_notification_test_requires_bot_token(
        self,
        mock_load_runtime_config: MagicMock,
    ) -> None:
        # Ensure user has keywords and telegram IDs
        from bsm.settings import upsert_access_user
        upsert_access_user(username="testadmin", password_hash="admin", keywords=["x"], telegram_ids=["1"], status="active")
        # Remove return_value setting for the removed mock
        mock_load_runtime_config.return_value = {"telegram": {"enabled": False, "bot_token": ""}}

        response = self.client.post(
            "/api/settings/user-notifications/test",
            auth=("testadmin", "admin"),
            json={"username": "testadmin"},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"], "telegram bot token is not configured")

    @patch("bsm.telegrambot.TelegramBot.send_text_to")
    @patch("bsm.settings.load_runtime_config")
    def test_user_notification_test_partial_failure(
        self,
        mock_load_runtime_config: MagicMock,
        mock_send_text_to: MagicMock,
    ) -> None:
        # Seed user with multiple IDs
        from bsm.settings import upsert_access_user
        upsert_access_user(
            username="testadmin", 
            password_hash="admin", 
            keywords=["x"], 
            telegram_ids=["10001", "10002"], 
            status="active"
        )
        # Remove return_value setting for the removed mock
        mock_load_runtime_config.return_value = {"telegram": {"enabled": True, "bot_token": "TEST_TOKEN"}}
        
        # First call succeeds, second fails
        mock_send_text_to.side_effect = [True, False]

        response = self.client.post(
            "/api/settings/user-notifications/test",
            auth=("testadmin", "admin"),
            json={"username": "testadmin"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["sent"], 1)
        self.assertEqual(data["failed_chat_ids"], ["10002"])

    def test_regular_user_can_read_own_notifications(self) -> None:
        response = self.client.get("/api/settings/user-notifications?username=demo", headers=self.user_headers)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["username"], "demo")

    def test_regular_user_cannot_read_other_user_notifications(self) -> None:
        response = self.client.get("/api/settings/user-notifications?username=testadmin", auth=("demo", "user1234"))

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "forbidden")

    def test_regular_user_cannot_update_other_user_notifications(self) -> None:
        response = self.client.put(
            "/api/settings/user-notifications",
            auth=("demo", "user1234"),
            json={
                "username": "testadmin",
                "notify_enabled": False,
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "forbidden")

    def test_regular_user_cannot_access_system_settings(self) -> None:
        response = self.client.get("/api/settings", auth=("demo", "user1234"))

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "Admin privileges required")

    def test_regular_user_cannot_access_db_size_diagnostics(self) -> None:
        response = self.client.get("/api/settings/db-size", auth=("demo", "user1234"))

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "Admin privileges required")

    def test_admin_can_read_session_picker_settings(self) -> None:
        response = self.client.get("/api/settings", auth=("testadmin", "admin"))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["app_base_url"], "")
        self.assertFalse(data["cloudflare_validation_enabled"])
        self.assertEqual(data["cloudflare_turnstile_site_key"], "")
        self.assertFalse(data["cloudflare_turnstile_secret_key_configured"])
        self.assertEqual(data["admin_telegram_ids"], [])
        self.assertEqual(data["bili_session_pick_mode"], "round_robin")
        self.assertEqual(data["bili_session_cooldown_seconds"], 60)

    def test_admin_can_update_admin_telegram_ids_and_app_base_url(self) -> None:
        response = self.client.put(
            "/api/settings",
            auth=("testadmin", "admin"),
            json={
                "app_base_url": "https://bsm.example.com/",
                "admin_telegram_ids": ["10001", "10002", "10001"],
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["updated"]["app_base_url"], "https://bsm.example.com")
        self.assertEqual(data["updated"]["admin_telegram_ids"], ["10001", "10002"])

        follow_up = self.client.get("/api/settings", auth=("testadmin", "admin"))
        self.assertEqual(follow_up.status_code, 200)
        refreshed = follow_up.json()
        self.assertEqual(refreshed["app_base_url"], "https://bsm.example.com")
        self.assertEqual(refreshed["admin_telegram_ids"], ["10001", "10002"])

    @patch("bsm.settings.save_yaml_config_value")
    def test_update_settings_returns_500_when_persist_fails(self, mock_save_yaml_config_value: MagicMock) -> None:
        mock_save_yaml_config_value.side_effect = PermissionError("read-only file system")

        response = self.client.put(
            "/api/settings",
            auth=("testadmin", "admin"),
            json={"app_base_url": "https://bsm.example.com"},
        )

        self.assertEqual(response.status_code, 500)
        data = response.json()
        self.assertIn("failed to save settings", data["error"])
        self.assertIn("app_base_url", data["error"])

    def test_admin_can_update_cloudflare_validation_settings(self) -> None:
        response = self.client.put(
            "/api/settings",
            auth=("testadmin", "admin"),
            json={
                "cloudflare_validation_enabled": True,
                "cloudflare_turnstile_site_key": "site-key",
                "cloudflare_turnstile_secret_key": "secret-key",
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["updated"]["cloudflare_validation_enabled"])
        self.assertEqual(data["updated"]["cloudflare_turnstile_site_key"], "site-key")
        self.assertTrue(data["updated"]["cloudflare_turnstile_secret_key_configured"])

        public_resp = self.client.get("/api/public/login-settings")
        self.assertEqual(public_resp.status_code, 200)
        public_data = public_resp.json()
        self.assertTrue(public_data["cloudflare_validation_enabled"])
        self.assertEqual(public_data["cloudflare_turnstile_site_key"], "site-key")

        admin_resp = self.client.get("/api/settings", auth=("testadmin", "admin"))
        self.assertEqual(admin_resp.status_code, 200)
        admin_data = admin_resp.json()
        self.assertTrue(admin_data["cloudflare_turnstile_secret_key_configured"])

    def test_all_selected_price_and_discount_filters_are_persisted_as_empty(self) -> None:
        all_price_filters = ["0-2000", "2000-3000", "3000-5000", "5000-10000", "10000-20000", "20000-0"]
        all_discount_filters = ["70-100", "50-70", "30-50", "0-30"]
        response = self.client.put(
            "/api/settings",
            auth=("testadmin", "admin"),
            json={
                "price_filters": all_price_filters,
                "discount_filters": all_discount_filters,
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["updated"]["price_filters"], [])
        self.assertEqual(data["updated"]["discount_filters"], [])

        from bsm.settings import load_yaml_config
        yaml_cfg = load_yaml_config()
        self.assertEqual(yaml_cfg.get("price_filters"), [])
        self.assertEqual(yaml_cfg.get("discount_filters"), [])

    def test_empty_persisted_filters_are_returned_as_all_selected(self) -> None:
        response = self.client.put(
            "/api/settings",
            auth=("testadmin", "admin"),
            json={
                "price_filters": [],
                "discount_filters": [],
            },
        )
        self.assertEqual(response.status_code, 200)

        follow_up = self.client.get("/api/settings", auth=("testadmin", "admin"))
        self.assertEqual(follow_up.status_code, 200)
        data = follow_up.json()
        self.assertEqual(data["price_filters"], ["0-2000", "2000-3000", "3000-5000", "5000-10000", "10000-20000", "20000-0"])
        self.assertEqual(data["discount_filters"], ["70-100", "50-70", "30-50", "0-30"])

    def test_admin_can_update_session_picker_settings(self) -> None:
        response = self.client.put(
            "/api/settings",
            auth=("testadmin", "admin"),
            json={
                "bili_session_pick_mode": "random",
                "bili_session_cooldown_seconds": 90,
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["updated"]["bili_session_pick_mode"], "random")
        self.assertEqual(data["updated"]["bili_session_cooldown_seconds"], 90)

        follow_up = self.client.get("/api/settings", auth=("testadmin", "admin"))
        self.assertEqual(follow_up.status_code, 200)
        refreshed = follow_up.json()
        self.assertEqual(refreshed["bili_session_pick_mode"], "random")
        self.assertEqual(refreshed["bili_session_cooldown_seconds"], 90)

    def test_admin_can_update_admin_scan_summary_interval_seconds(self) -> None:
        response = self.client.put(
            "/api/settings",
            auth=("testadmin", "admin"),
            json={"admin_scan_summary_interval_seconds": 300},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["updated"]["admin_scan_summary_interval_seconds"], 300)

        follow_up = self.client.get("/api/settings", auth=("testadmin", "admin"))
        self.assertEqual(follow_up.status_code, 200)
        refreshed = follow_up.json()
        self.assertEqual(refreshed["admin_scan_summary_interval_seconds"], 300)

    def test_admin_cannot_set_invalid_session_picker_mode(self) -> None:
        response = self.client.put(
            "/api/settings",
            auth=("testadmin", "admin"),
            json={"bili_session_pick_mode": "broken"},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["error"],
            "bili_session_pick_mode must be 'round_robin' or 'random'",
        )

    def test_admin_cannot_set_negative_session_cooldown(self) -> None:
        response = self.client.put(
            "/api/settings",
            auth=("testadmin", "admin"),
            json={"bili_session_cooldown_seconds": -1},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["error"],
            "bili_session_cooldown_seconds must be >= 0",
        )

    def test_missing_auth_is_rejected(self) -> None:
        response = self.client.get("/api/settings/user-notifications?username=demo")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Not authenticated")

    def test_user_settings_endpoint(self) -> None:
        """Verify that a regular user can access the public settings endpoint."""
        response = self.client.get("/api/account/settings", headers=self.user_headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("interval", data)
        self.assertNotIn("bot_id", data)

if __name__ == "__main__":
    unittest.main()
