import os
import sys
import unittest
from unittest.mock import MagicMock, patch


PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
SRC_ROOT = os.path.join(PROJECT_ROOT, "src")
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if SRC_ROOT not in sys.path:
    sys.path.insert(0, SRC_ROOT)

from backend import cron_runner


class CronRunnerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        cron_runner._SCAN_CATEGORY_INDEX = 0
        cron_runner._CATEGORY_SCAN_STATE.clear()
        cron_runner._CATEGORY_SESSION_BINDINGS.clear()
        cron_runner._CATEGORY_SLEEP_STATE.clear()

    def tearDown(self) -> None:
        cron_runner._SCAN_CATEGORY_INDEX = 0
        cron_runner._CATEGORY_SCAN_STATE.clear()
        cron_runner._CATEGORY_SESSION_BINDINGS.clear()
        cron_runner._CATEGORY_SLEEP_STATE.clear()

    def test_build_admin_scan_summary_message(self) -> None:
        bucket = {}
        cron_runner._accumulate_admin_scan_summary(bucket, {
            "category_key": "2312",
            "category_label": "手办",
            "count": 12,
            "inserted": 3,
            "did_reset_cursor": True,
        })
        cron_runner._accumulate_admin_scan_summary(bucket, {
            "category_key": "2066",
            "category_label": "模型",
            "count": 7,
            "inserted": 2,
            "did_reset_cursor": False,
        })
        cron_runner._accumulate_admin_scan_summary(bucket, {
            "category_key": "2312",
            "category_label": "手办",
            "count": 5,
            "inserted": 1,
            "did_reset_cursor": True,
        })

        msg = cron_runner._build_admin_scan_summary_message(bucket)
        self.assertEqual(
            msg,
            "10分钟新增\n手办 4 条 | 重置 2 次 | 合计 17 条\n模型 2 条 | 重置 0 次 | 合计 7 条",
        )

    def test_category_sleep_backoff_increases_and_caps(self) -> None:
        for _ in range(10):
            cron_runner._update_category_sleep_state("2312", True)

        state = cron_runner._CATEGORY_SLEEP_STATE["2312"]
        self.assertEqual(state["level"], 6)
        self.assertEqual(state["remaining"], 6)

        cron_runner._update_category_sleep_state("2312", False)
        reset_state = cron_runner._CATEGORY_SLEEP_STATE["2312"]
        self.assertEqual(reset_state["level"], 0)
        self.assertEqual(reset_state["remaining"], 0)

    def test_category_sleep_consumes_rounds(self) -> None:
        cron_runner._CATEGORY_SLEEP_STATE["2312"] = {"level": 3, "remaining": 2}

        self.assertFalse(cron_runner._should_scan_category_this_round("2312"))
        self.assertEqual(cron_runner._CATEGORY_SLEEP_STATE["2312"]["remaining"], 1)
        self.assertFalse(cron_runner._should_scan_category_this_round("2312"))
        self.assertEqual(cron_runner._CATEGORY_SLEEP_STATE["2312"]["remaining"], 0)
        self.assertTrue(cron_runner._should_scan_category_this_round("2312"))

    @patch("bsm.notify.load_notifier")
    @patch("bsm.scan.scan_once")
    @patch("bsm.db.mark_bili_session_result")
    @patch("bsm.db.record_bili_session_fetch_success")
    @patch("bsm.db.save_items")
    @patch("bsm.db.filter_new_items")
    @patch("bsm.db.list_bili_sessions")
    @patch("bsm.settings.load_runtime_config")
    def test_continue_mode_uses_in_memory_cursor_and_notifies_only_new_items(
        self,
        mock_load_runtime_config: MagicMock,
        mock_list_bili_sessions: MagicMock,
        mock_filter_new_items: MagicMock,
        mock_save_items: MagicMock,
        mock_record_fetch: MagicMock,
        mock_mark_result: MagicMock,
        mock_scan_once: MagicMock,
        mock_load_notifier: MagicMock,
    ) -> None:
        mock_load_runtime_config.return_value = {
            "interval": 60,
            "scan_mode": "continue",
            "category": "2312",
            "sort_type": "TIME_DESC",
            "notify": {},
        }
        mock_list_bili_sessions.return_value = [{
            "cookies": "cookie",
            "login_username": "tester",
            "status": "active",
            "last_error": None,
            "last_checked_at": None,
        }]
        first_items = [{"c2cItemsId": 1}, {"c2cItemsId": 2}]
        second_items = [{"c2cItemsId": 3}]
        mock_scan_once.side_effect = [
            ("cursor-1", first_items),
            (None, second_items),
        ]
        mock_filter_new_items.side_effect = [
            first_items,
            second_items,
        ]
        mock_save_items.side_effect = [
            (2, 1),
            (1, 1),
        ]
        notifier = MagicMock()
        mock_load_notifier.return_value = notifier

        with patch("backend.cron_runner.cron_state.info") as mock_info:
            first = cron_runner._run_scan_once()
            second = cron_runner._run_scan_once()

        self.assertEqual(first["inserted"], 1)
        self.assertEqual(second["inserted"], 1)
        self.assertEqual(mock_scan_once.call_args_list[1].args[2], "cursor-1")
        self.assertEqual(cron_runner._CATEGORY_SCAN_STATE["2312"]["next_id"], None)
        self.assertEqual(cron_runner._CATEGORY_SCAN_STATE["2312"]["page_count"], 0)
        self.assertEqual(notifier.notify_batch.call_args_list[0].args[0], first_items)
        self.assertEqual(notifier.notify_batch.call_args_list[1].args[0], second_items)
        self.assertEqual(mock_record_fetch.call_count, 2)
        self.assertEqual(mock_mark_result.call_count, 2)
        info_messages = [call.args[0] for call in mock_info.call_args_list]
        self.assertTrue(any("开始扫描 | 账号 tester | 分类 手办 | 模式 continue | 第 " in message for message in info_messages))
        self.assertTrue(any("扫描完成 | 分类 手办 | 模式 continue | 第 " in message and "| 2 条 | 新增 1 条" in message for message in info_messages))
        self.assertTrue(any("扫描完成 | 分类 手办 | 模式 continue | 第 " in message and "| 耗时 API " in message and "| DB " in message for message in info_messages))
        self.assertTrue(any("下次扫描 | 分类 手办 | 第 " in message for message in info_messages))

    @patch("bsm.notify.load_notifier")
    @patch("bsm.scan.scan_once")
    @patch("bsm.db.mark_bili_session_result")
    @patch("bsm.db.record_bili_session_fetch_success")
    @patch("bsm.db.save_items")
    @patch("bsm.db.filter_new_items")
    @patch("bsm.db.list_bili_sessions")
    @patch("bsm.settings.load_runtime_config")
    def test_continue_until_repeat_resets_cursor_when_page_contains_existing_items(
        self,
        mock_load_runtime_config: MagicMock,
        mock_list_bili_sessions: MagicMock,
        mock_filter_new_items: MagicMock,
        mock_save_items: MagicMock,
        mock_record_fetch: MagicMock,
        mock_mark_result: MagicMock,
        mock_scan_once: MagicMock,
        mock_load_notifier: MagicMock,
    ) -> None:
        mock_load_runtime_config.return_value = {
            "interval": 60,
            "scan_mode": "continue_until_repeat",
            "category": "2312",
            "sort_type": "TIME_DESC",
            "notify": {},
        }
        mock_list_bili_sessions.return_value = [{
            "cookies": "cookie",
            "login_username": "tester",
            "status": "active",
            "last_error": None,
            "last_checked_at": None,
        }]
        items = [{"c2cItemsId": 1}, {"c2cItemsId": 2}]
        mock_scan_once.return_value = ("cursor-2", items)
        mock_filter_new_items.return_value = [items[0]]
        mock_save_items.return_value = (2, 1)
        notifier = MagicMock()
        mock_load_notifier.return_value = notifier

        with patch("backend.cron_runner.cron_state.info") as mock_info:
            result = cron_runner._run_scan_once()

        self.assertEqual(result["inserted"], 1)
        self.assertEqual(mock_scan_once.call_args.args[2], None)
        self.assertEqual(cron_runner._CATEGORY_SCAN_STATE["2312"]["next_id"], None)
        self.assertEqual(cron_runner._CATEGORY_SCAN_STATE["2312"]["page_count"], 0)
        self.assertEqual(notifier.notify_batch.call_args.args[0], [items[0]])
        self.assertEqual(mock_record_fetch.call_count, 1)
        self.assertEqual(mock_mark_result.call_count, 1)
        info_messages = [call.args[0] for call in mock_info.call_args_list]
        self.assertTrue(any("开始扫描 | 账号 tester | 分类 手办 | 模式 CUR | 第 1 页" in message for message in info_messages))
        self.assertTrue(any("扫描完成 | 分类 手办 | 模式 CUR | 第 1 页 | 2 条 | 新增 1 条" in message for message in info_messages))
        self.assertTrue(any("扫描完成 | 分类 手办 | 模式 CUR | 第 1 页 | 2 条 | 新增 1 条" in message and "| 耗时 API " in message and "| DB " in message for message in info_messages))
        self.assertTrue(any("下次扫描 | 分类 手办 | 第 1 页" in message for message in info_messages))

    @patch("bsm.notify.load_notifier")
    @patch("bsm.scan.scan_once")
    @patch("bsm.db.mark_bili_session_result")
    @patch("bsm.db.record_bili_session_fetch_success")
    @patch("bsm.db.save_items")
    @patch("bsm.db.filter_new_items")
    @patch("bsm.db.list_bili_sessions")
    @patch("bsm.settings.load_runtime_config")
    def test_multiple_categories_scan_in_same_round_and_keep_separate_cursor_state(
        self,
        mock_load_runtime_config: MagicMock,
        mock_list_bili_sessions: MagicMock,
        mock_filter_new_items: MagicMock,
        mock_save_items: MagicMock,
        mock_record_fetch: MagicMock,
        mock_mark_result: MagicMock,
        mock_scan_once: MagicMock,
        mock_load_notifier: MagicMock,
    ) -> None:
        mock_load_runtime_config.return_value = {
            "interval": 60,
            "scan_mode": "continue",
            "category": "2312,2066",
            "sort_type": "TIME_DESC",
            "notify": {},
        }
        mock_list_bili_sessions.return_value = [{
            "cookies": "cookie",
            "login_username": "tester",
            "status": "active",
            "last_error": None,
            "last_checked_at": None,
        }]
        mock_scan_once.side_effect = [
            ("cursor-a", [{"c2cItemsId": 1}]),
            ("cursor-b", [{"c2cItemsId": 2}]),
            (None, [{"c2cItemsId": 3}]),
            ("cursor-d", [{"c2cItemsId": 4}]),
        ]
        mock_filter_new_items.side_effect = [
            [{"c2cItemsId": 1}],
            [{"c2cItemsId": 2}],
            [{"c2cItemsId": 3}],
            [{"c2cItemsId": 4}],
        ]
        mock_save_items.side_effect = [
            (1, 1),
            (1, 1),
            (1, 1),
            (1, 1),
        ]
        notifier = MagicMock()
        mock_load_notifier.return_value = notifier

        with patch("backend.cron_runner.cron_state.info") as mock_info:
            cron_runner._run_scan_once()
            cron_runner._run_scan_once()

        self.assertEqual(mock_scan_once.call_args_list[0].args[1]["category"], "2312")
        self.assertEqual(mock_scan_once.call_args_list[1].args[1]["category"], "2066")
        self.assertEqual(mock_scan_once.call_args_list[2].args[1]["category"], "2312")
        self.assertEqual(mock_scan_once.call_args_list[3].args[1]["category"], "2066")
        self.assertEqual(mock_scan_once.call_args_list[0].args[2], None)
        self.assertEqual(mock_scan_once.call_args_list[1].args[2], None)
        self.assertEqual(mock_scan_once.call_args_list[2].args[2], "cursor-a")
        self.assertEqual(mock_scan_once.call_args_list[3].args[2], "cursor-b")
        self.assertEqual(cron_runner._CATEGORY_SCAN_STATE["2312"]["next_id"], None)
        self.assertEqual(cron_runner._CATEGORY_SCAN_STATE["2312"]["page_count"], 0)
        self.assertEqual(cron_runner._CATEGORY_SCAN_STATE["2066"]["next_id"], "cursor-d")
        self.assertEqual(cron_runner._CATEGORY_SCAN_STATE["2066"]["page_count"], 2)
        info_messages = [call.args[0] for call in mock_info.call_args_list]
        self.assertTrue(any("开始扫描 | 账号 tester | 分类 手办 | 模式 continue | 第 1 页" in message for message in info_messages))
        self.assertTrue(any("开始扫描 | 账号 tester | 分类 模型 | 模式 continue | 第 1 页" in message for message in info_messages))

    @patch("bsm.notify.load_notifier")
    @patch("bsm.scan.scan_once")
    @patch("bsm.db.mark_bili_session_result")
    @patch("bsm.db.record_bili_session_fetch_success")
    @patch("bsm.db.save_items")
    @patch("bsm.db.filter_new_items")
    @patch("bsm.db.list_bili_sessions")
    @patch("bsm.settings.load_runtime_config")
    def test_cur_resets_after_50_pages(
        self,
        mock_load_runtime_config: MagicMock,
        mock_list_bili_sessions: MagicMock,
        mock_filter_new_items: MagicMock,
        mock_save_items: MagicMock,
        mock_record_fetch: MagicMock,
        mock_mark_result: MagicMock,
        mock_scan_once: MagicMock,
        mock_load_notifier: MagicMock,
    ) -> None:
        cron_runner._CATEGORY_SCAN_STATE["2312"] = {"next_id": "cursor-49", "page_count": 49}
        mock_load_runtime_config.return_value = {
            "interval": 60,
            "scan_mode": "continue_until_repeat",
            "category": "2312",
            "sort_type": "TIME_DESC",
            "notify": {},
        }
        mock_list_bili_sessions.return_value = [{
            "cookies": "cookie",
            "login_username": "tester",
            "status": "active",
            "last_error": None,
            "last_checked_at": None,
        }]
        items = [{"c2cItemsId": 1}]
        mock_scan_once.return_value = ("cursor-50", items)
        mock_filter_new_items.return_value = items
        mock_save_items.return_value = (1, 1)
        notifier = MagicMock()
        mock_load_notifier.return_value = notifier

        with patch("backend.cron_runner.cron_state.info") as mock_info:
            cron_runner._run_scan_once()

        self.assertEqual(mock_scan_once.call_args.args[2], "cursor-49")
        self.assertEqual(cron_runner._CATEGORY_SCAN_STATE["2312"]["next_id"], None)
        self.assertEqual(cron_runner._CATEGORY_SCAN_STATE["2312"]["page_count"], 0)
        info_messages = [call.args[0] for call in mock_info.call_args_list]
        self.assertTrue(any("开始扫描 | 账号 tester | 分类 手办 | 模式 CUR | 第 50 页" in message for message in info_messages))
        self.assertTrue(any("下次扫描 | 分类 手办 | 第 1 页" in message for message in info_messages))


if __name__ == "__main__":
    unittest.main()
