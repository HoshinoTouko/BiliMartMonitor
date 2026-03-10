import os
import sys
import asyncio
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


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
        cron_runner._reset_session_cache()
        cron_runner._FINALIZE_RESULT_QUEUE = None
        cron_runner._FINALIZE_TASKS.clear()

    def tearDown(self) -> None:
        if cron_runner._FINALIZE_TASKS:
            asyncio.run(asyncio.gather(*list(cron_runner._FINALIZE_TASKS), return_exceptions=True))
            cron_runner._FINALIZE_TASKS.clear()
        cron_runner._SCAN_CATEGORY_INDEX = 0
        cron_runner._CATEGORY_SCAN_STATE.clear()
        cron_runner._CATEGORY_SESSION_BINDINGS.clear()
        cron_runner._CATEGORY_SLEEP_STATE.clear()
        cron_runner._reset_session_cache()
        cron_runner._FINALIZE_RESULT_QUEUE = None

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
    @patch("bsm.scan.scan_once_async", new_callable=AsyncMock)
    @patch("bsm.db.apply_bili_session_scan_results")
    @patch("bsm.db.save_items_data_phase")
    @patch("bsm.db.list_bili_sessions")
    @patch("bsm.settings.load_runtime_config")
    def test_continue_mode_uses_in_memory_cursor_and_notifies_only_new_items(
        self,
        mock_load_runtime_config: MagicMock,
        mock_list_bili_sessions: MagicMock,
        mock_save_items_data_phase: MagicMock,
        mock_apply_scan_results: MagicMock,
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
        mock_save_items_data_phase.side_effect = [
            {"saved": 2, "inserted": 1, "data_write_ms": 1, "blob_write_ms": 0, "blob_write_count": 1, "new_items": first_items},
            {"saved": 1, "inserted": 1, "data_write_ms": 1, "blob_write_ms": 0, "blob_write_count": 1, "new_items": second_items},
        ]
        notifier = MagicMock()
        mock_load_notifier.return_value = notifier

        with patch("backend.cron_runner.cron_state.info") as mock_info:
            first = asyncio.run(cron_runner._run_scan_once())
            second = asyncio.run(cron_runner._run_scan_once())

        self.assertEqual(first["inserted"], 1)
        self.assertEqual(second["inserted"], 1)
        self.assertEqual(mock_scan_once.call_args_list[1].args[2], "cursor-1")
        self.assertEqual(cron_runner._CATEGORY_SCAN_STATE["2312"]["next_id"], None)
        self.assertEqual(cron_runner._CATEGORY_SCAN_STATE["2312"]["page_count"], 0)
        self.assertEqual(notifier.notify_batch.call_args_list[0].args[0], first_items)
        self.assertEqual(notifier.notify_batch.call_args_list[1].args[0], second_items)
        self.assertEqual(mock_apply_scan_results.call_count, 2)
        info_messages = [call.args[0] for call in mock_info.call_args_list]
        self.assertTrue(any("开始扫描 | 账号 tester | 分类 手办 | 模式 continue | 第 " in message for message in info_messages))
        self.assertTrue(any("扫描完成 | 分类 手办 | 模式 continue | 第 " in message and "| 2 条 | 新增 1 条" in message for message in info_messages))
        self.assertTrue(any("扫描完成 | 分类 手办 | 模式 continue | 第 " in message and "| 耗时 API " in message and "| DB " in message for message in info_messages))
        self.assertTrue(any("下次扫描 | 分类 手办 | 第 " in message for message in info_messages))

    @patch("bsm.notify.load_notifier")
    @patch("bsm.scan.scan_once_async", new_callable=AsyncMock)
    @patch("bsm.db.apply_bili_session_scan_results")
    @patch("bsm.db.save_items_data_phase")
    @patch("bsm.db.list_bili_sessions")
    @patch("bsm.settings.load_runtime_config")
    def test_continue_until_repeat_resets_cursor_when_page_contains_existing_items(
        self,
        mock_load_runtime_config: MagicMock,
        mock_list_bili_sessions: MagicMock,
        mock_save_items_data_phase: MagicMock,
        mock_apply_scan_results: MagicMock,
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
        mock_save_items_data_phase.return_value = {
            "saved": 2,
            "inserted": 1,
            "data_write_ms": 1,
            "blob_write_ms": 0,
            "blob_write_count": 1,
            "new_items": [items[0]],
        }
        notifier = MagicMock()
        mock_load_notifier.return_value = notifier

        with patch("backend.cron_runner.cron_state.info") as mock_info:
            result = asyncio.run(cron_runner._run_scan_once())

        self.assertEqual(result["inserted"], 1)
        self.assertEqual(mock_scan_once.call_args.args[2], None)
        self.assertEqual(cron_runner._CATEGORY_SCAN_STATE["2312"]["next_id"], None)
        self.assertEqual(cron_runner._CATEGORY_SCAN_STATE["2312"]["page_count"], 0)
        self.assertEqual(notifier.notify_batch.call_args.args[0], [items[0]])
        self.assertEqual(mock_apply_scan_results.call_count, 1)
        info_messages = [call.args[0] for call in mock_info.call_args_list]
        self.assertTrue(any("开始扫描 | 账号 tester | 分类 手办 | 模式 CUR | 第 1 页" in message for message in info_messages))
        self.assertTrue(any("扫描完成 | 分类 手办 | 模式 CUR | 第 1 页 | 2 条 | 新增 1 条" in message for message in info_messages))
        self.assertTrue(any("扫描完成 | 分类 手办 | 模式 CUR | 第 1 页 | 2 条 | 新增 1 条" in message and "| 耗时 API " in message and "| DB " in message for message in info_messages))
        self.assertTrue(any("下次扫描 | 分类 手办 | 第 1 页" in message for message in info_messages))

    @patch("bsm.notify.load_notifier")
    @patch("bsm.scan.scan_once_async", new_callable=AsyncMock)
    @patch("bsm.db.apply_bili_session_scan_results")
    @patch("bsm.db.save_items_data_phase")
    @patch("bsm.db.list_bili_sessions")
    @patch("bsm.settings.load_runtime_config")
    def test_cur_does_not_reset_when_unpersistable_rows_exist_but_saved_rows_are_all_new(
        self,
        mock_load_runtime_config: MagicMock,
        mock_list_bili_sessions: MagicMock,
        mock_save_items_data_phase: MagicMock,
        mock_apply_scan_results: MagicMock,
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
        items = [{"c2cItemsId": 1}, {"invalid": True}]
        mock_scan_once.return_value = ("cursor-2", items)
        mock_save_items_data_phase.return_value = {
            "saved": 1,
            "inserted": 1,
            "data_write_ms": 1,
            "blob_write_ms": 0,
            "blob_write_count": 1,
            "new_items": [items[0]],
        }
        notifier = MagicMock()
        mock_load_notifier.return_value = notifier

        result = asyncio.run(cron_runner._run_scan_once())

        self.assertEqual(result["inserted"], 1)
        self.assertEqual(cron_runner._CATEGORY_SCAN_STATE["2312"]["next_id"], "cursor-2")
        self.assertEqual(cron_runner._CATEGORY_SCAN_STATE["2312"]["page_count"], 1)
        self.assertEqual(mock_apply_scan_results.call_count, 1)

    @patch("bsm.notify.load_notifier")
    @patch("bsm.scan.scan_once_async", new_callable=AsyncMock)
    @patch("bsm.db.apply_bili_session_scan_results")
    @patch("bsm.db.save_items_data_phase")
    @patch("bsm.db.list_bili_sessions")
    @patch("bsm.settings.load_runtime_config")
    def test_multiple_categories_scan_in_same_round_and_keep_separate_cursor_state(
        self,
        mock_load_runtime_config: MagicMock,
        mock_list_bili_sessions: MagicMock,
        mock_save_items_data_phase: MagicMock,
        mock_apply_scan_results: MagicMock,
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
        mock_save_items_data_phase.side_effect = [
            {"saved": 1, "inserted": 1, "data_write_ms": 1, "blob_write_ms": 0, "blob_write_count": 1, "new_items": [{"c2cItemsId": 1}]},
            {"saved": 1, "inserted": 1, "data_write_ms": 1, "blob_write_ms": 0, "blob_write_count": 1, "new_items": [{"c2cItemsId": 2}]},
            {"saved": 1, "inserted": 1, "data_write_ms": 1, "blob_write_ms": 0, "blob_write_count": 1, "new_items": [{"c2cItemsId": 3}]},
            {"saved": 1, "inserted": 1, "data_write_ms": 1, "blob_write_ms": 0, "blob_write_count": 1, "new_items": [{"c2cItemsId": 4}]},
        ]
        notifier = MagicMock()
        mock_load_notifier.return_value = notifier

        with patch("backend.cron_runner.cron_state.info") as mock_info:
            asyncio.run(cron_runner._run_scan_once())
            asyncio.run(cron_runner._run_scan_once())

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
    @patch("bsm.scan.scan_once_async", new_callable=AsyncMock)
    @patch("bsm.db.apply_bili_session_scan_results")
    @patch("bsm.db.save_items_data_phase")
    @patch("bsm.db.list_bili_sessions")
    @patch("bsm.settings.load_runtime_config")
    def test_cur_resets_after_50_pages(
        self,
        mock_load_runtime_config: MagicMock,
        mock_list_bili_sessions: MagicMock,
        mock_save_items_data_phase: MagicMock,
        mock_apply_scan_results: MagicMock,
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
        mock_save_items_data_phase.return_value = {
            "saved": 1,
            "inserted": 1,
            "data_write_ms": 1,
            "blob_write_ms": 0,
            "blob_write_count": 1,
            "new_items": items,
        }
        notifier = MagicMock()
        mock_load_notifier.return_value = notifier

        with patch("backend.cron_runner.cron_state.info") as mock_info:
            asyncio.run(cron_runner._run_scan_once())

        self.assertEqual(mock_scan_once.call_args.args[2], "cursor-49")
        self.assertEqual(cron_runner._CATEGORY_SCAN_STATE["2312"]["next_id"], None)
        self.assertEqual(cron_runner._CATEGORY_SCAN_STATE["2312"]["page_count"], 0)
        info_messages = [call.args[0] for call in mock_info.call_args_list]
        self.assertTrue(any("开始扫描 | 账号 tester | 分类 手办 | 模式 CUR | 第 50 页" in message for message in info_messages))
        self.assertTrue(any("下次扫描 | 分类 手办 | 第 1 页" in message for message in info_messages))

    @patch("bsm.notify.load_notifier")
    @patch("bsm.scan.scan_once_async", new_callable=AsyncMock)
    @patch("bsm.db.apply_bili_session_scan_results")
    @patch("bsm.db.save_items_data_phase")
    @patch("bsm.db.list_bili_sessions")
    @patch("bsm.settings.load_runtime_config")
    def test_deferred_finalize_returns_before_slow_db_and_publishes_result(
        self,
        mock_load_runtime_config: MagicMock,
        mock_list_bili_sessions: MagicMock,
        mock_save_items_data_phase: MagicMock,
        mock_apply_scan_results: MagicMock,
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
        items = [{"c2cItemsId": 1}]
        mock_scan_once.return_value = ("cursor-1", items)
        def _slow_save(job_items: list[dict]) -> dict[str, int]:
            time.sleep(0.25)
            return {
                "saved": len(job_items),
                "inserted": len(job_items),
                "data_write_ms": 250,
                "blob_write_ms": 0,
                "blob_write_count": len(job_items),
                "new_items": list(job_items),
            }

        mock_save_items_data_phase.side_effect = _slow_save
        notifier = MagicMock()
        mock_load_notifier.return_value = notifier

        async def _run() -> tuple[dict[str, object], float, dict[str, object]]:
            cron_runner._FINALIZE_RESULT_QUEUE = asyncio.Queue()
            started_at = time.perf_counter()
            result = await cron_runner._run_scan_once(defer_db_finalize=True)
            elapsed = time.perf_counter() - started_at
            self.assertTrue(result.get("deferred"))
            self.assertLess(elapsed, 0.2, "deferred mode should return before slow DB finalize completes")

            if cron_runner._FINALIZE_TASKS:
                await asyncio.gather(*list(cron_runner._FINALIZE_TASKS), return_exceptions=True)
            finalized = await asyncio.wait_for(cron_runner._FINALIZE_RESULT_QUEUE.get(), timeout=1.0)
            return result, elapsed, finalized

        result, elapsed, finalized = asyncio.run(_run())
        self.assertTrue(result["deferred"])
        self.assertLess(elapsed, 0.2)
        self.assertEqual(finalized["inserted"], 1)
        self.assertEqual(finalized["count"], 1)
        self.assertEqual(mock_apply_scan_results.call_count, 1)
        self.assertEqual(notifier.notify_batch.call_count, 1)

    def test_cron_loop_counts_interval_from_dispatch_time(self) -> None:
        call_times: list[float] = []

        async def _fake_run_scan_once(*, defer_db_finalize: bool = False) -> dict[str, object]:
            self.assertFalse(defer_db_finalize)
            call_times.append(time.monotonic())
            if len(call_times) == 1:
                await asyncio.sleep(0.25)
                return {
                    "skip": True,
                    "interval": 0.2,
                    "admin_scan_summary_interval_seconds": 600,
                }
            raise asyncio.CancelledError()

        with patch("backend.cron_runner._run_scan_once", new=AsyncMock(side_effect=_fake_run_scan_once)):
            asyncio.run(cron_runner.cron_loop())

        self.assertGreaterEqual(len(call_times), 2)
        # If interval is counted from dispatch start (not from completion), second dispatch should
        # start almost immediately after the first scan call returns (~0.25s), not +0.2s later (~0.45s).
        self.assertLess(call_times[1] - call_times[0], 0.35)

    @patch("backend.cron_runner._refresh_session_cache")
    @patch("bsm.notify.load_notifier")
    @patch("bsm.scan.scan_once_async", new_callable=AsyncMock)
    @patch("bsm.db.apply_bili_session_scan_results")
    @patch("bsm.db.save_items_data_phase")
    @patch("bsm.db.list_bili_sessions")
    @patch("bsm.settings.load_runtime_config")
    def test_session_failure_triggers_cache_refresh(
        self,
        mock_load_runtime_config: MagicMock,
        mock_list_bili_sessions: MagicMock,
        mock_save_items_data_phase: MagicMock,
        mock_apply_scan_results: MagicMock,
        mock_scan_once: MagicMock,
        mock_load_notifier: MagicMock,
        mock_refresh_session_cache: MagicMock,
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
        mock_scan_once.side_effect = Exception("cookie expired")
        mock_save_items_data_phase.return_value = {
            "saved": 0,
            "inserted": 0,
            "data_write_ms": 0,
            "blob_write_ms": 0,
            "blob_write_count": 0,
            "new_items": [],
        }
        mock_refresh_session_cache.return_value = mock_list_bili_sessions.return_value
        notifier = MagicMock()
        mock_load_notifier.return_value = notifier

        asyncio.run(cron_runner._run_scan_once())

        self.assertEqual(mock_apply_scan_results.call_count, 1)
        self.assertEqual(mock_refresh_session_cache.call_count, 1)


if __name__ == "__main__":
    unittest.main()
