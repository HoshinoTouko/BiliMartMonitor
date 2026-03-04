"""
Cron background task — scan loop without Telegram.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import sys
from pathlib import Path

_SRC_ROOT = str(Path(__file__).resolve().parent.parent / "src")
if _SRC_ROOT not in sys.path:
    sys.path.insert(0, _SRC_ROOT)

from backend.cron_state import cron_state  # noqa: E402

_CONTINUE_MAX_PAGES = 50
_CUR_MAX_PAGES = 30
_SCAN_TIMEOUT_SECONDS = 30
_SCAN_CATEGORY_INDEX = 0
_CATEGORY_SCAN_STATE: dict[str, dict[str, int | str | None]] = {}
_CATEGORY_LABELS = {
    "2312": "手办",
    "2066": "模型",
    "2331": "周边",
    "2273": "3C",
    "fudai_cate_id": "福袋",
}
_SCAN_NOW_EVENT: asyncio.Event | None = None
_CRON_LOOP: asyncio.AbstractEventLoop | None = None


def _mode_log_label(mode: str) -> str:
    if mode == "continue_until_repeat":
        return "CUR"
    return mode


def _normalize_categories(raw_category: str | None) -> list[str | None]:
    values = [item.strip() for item in str(raw_category or "").split(",") if item.strip()]
    return values or [None]


def _category_key(category: str | None) -> str:
    return category or ""


def _category_label(category: str | None) -> str:
    if category is None:
        return "全部"
    return _CATEGORY_LABELS.get(category, category)


def _next_category(categories: list[str | None]) -> str | None:
    global _SCAN_CATEGORY_INDEX

    if len(categories) == 1:
        _SCAN_CATEGORY_INDEX = 0
        return categories[0]
    category = categories[_SCAN_CATEGORY_INDEX % len(categories)]
    _SCAN_CATEGORY_INDEX = (_SCAN_CATEGORY_INDEX + 1) % len(categories)
    return category


def _peek_next_category(categories: list[str | None]) -> str | None:
    if len(categories) == 1:
        return categories[0]
    return categories[_SCAN_CATEGORY_INDEX % len(categories)]


def _get_category_state(category: str | None) -> dict[str, int | str | None]:
    return _CATEGORY_SCAN_STATE.setdefault(_category_key(category), {"next_id": None, "page_count": 0})


def _clear_category_state(category: str | None) -> None:
    state = _get_category_state(category)
    state["next_id"] = None
    state["page_count"] = 0


def _clear_all_category_states() -> None:
    for state in _CATEGORY_SCAN_STATE.values():
        state["next_id"] = None
        state["page_count"] = 0


def _mode_page(mode: str, category: str | None) -> int:
    if mode in {"continue", "continue_until_repeat"}:
        state = _get_category_state(category)
        return int(state["page_count"]) + 1
    return 1


def _max_pages_for_mode(mode: str) -> int:
    if mode == "continue_until_repeat":
        return _CUR_MAX_PAGES
    return _CONTINUE_MAX_PAGES


def request_scan_now() -> bool:
    if not cron_state.is_running:
        return False
    if _CRON_LOOP is None or _SCAN_NOW_EVENT is None:
        return False
    _CRON_LOOP.call_soon_threadsafe(_SCAN_NOW_EVENT.set)
    cron_state.info("已手动触发下一次扫描")
    return True


def reset_scan_progress() -> None:
    global _SCAN_CATEGORY_INDEX

    _SCAN_CATEGORY_INDEX = 0
    _CATEGORY_SCAN_STATE.clear()
    cron_state.info("扫描进度已重置")


def _run_scan_once() -> dict:
    """Blocking scan — runs in a thread executor (bsm code is synchronous)."""
    from bsm.settings import load_runtime_config
    from bsm.db import (
        filter_new_items,
        load_next_bili_session,
        save_items,
        record_bili_session_fetch_success,
        mark_bili_session_result,
    )
    from bsm.scan import scan_once, ScanRateLimitedError
    from bsm.notify import load_notifier, send_admin_telegram_alert

    global _SCAN_CATEGORY_INDEX

    cfg = load_runtime_config()
    interval = cfg.get("interval", 20)

    sess = load_next_bili_session()
    if not sess or not sess.get("cookies"):
        cron_state.warn("跳过：无可用 session，请先登录")
        return {"skip": True, "interval": interval}

    cookies = sess["cookies"]
    login_username = sess.get("login_username", "")
    mode = cfg.get("scan_mode", "latest")
    categories = _normalize_categories(cfg.get("category"))
    active_category = _next_category(categories)
    active_state = _get_category_state(active_category)
    page = _mode_page(mode, active_category)
    mode_label = _mode_log_label(mode)

    cron_state.info(
        f"开始扫描 | 账号 {login_username or '未知'} | 分类 {_category_label(active_category)} | 模式 {mode_label} | 第 {page} 页"
    )

    try:
        continue_like_mode = mode in {"continue", "continue_until_repeat"}
        scan_next_id = active_state["next_id"] if continue_like_mode else None
        scan_cfg = dict(cfg)
        scan_cfg["category"] = active_category or ""
        scan_cfg["scan_timeout_seconds"] = _SCAN_TIMEOUT_SECONDS
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(scan_once, cookies, scan_cfg, scan_next_id)
            next_id, items = future.result(timeout=_SCAN_TIMEOUT_SECONDS)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        new_items = filter_new_items(items)
        saved, inserted = save_items(items)
        should_reset_on_repeat = mode == "continue_until_repeat" and len(new_items) < len(items)
        should_reset = True
        max_pages = _max_pages_for_mode(mode)

        if continue_like_mode:
            next_page_count = int(active_state["page_count"]) + 1
            active_state["page_count"] = next_page_count
            if should_reset_on_repeat:
                should_reset = True
            elif next_id is None:
                should_reset = True
            elif next_page_count >= max_pages:
                should_reset = True
            else:
                should_reset = False
            if should_reset:
                _clear_category_state(active_category)
            else:
                active_state["next_id"] = next_id
        else:
            _clear_all_category_states()

        if login_username:
            record_bili_session_fetch_success(login_username, fetched_count=len(items))
            mark_bili_session_result(login_username, None)

        cron_state.info(
            f"扫描完成 | 分类 {_category_label(active_category)} | 模式 {mode_label} | 第 {page} 页 | {len(items)} 条 | 新增 {inserted} 条"
        )
        next_category = _peek_next_category(categories)
        next_page = _mode_page(mode, next_category)
        cron_state.info(f"下次扫描 | 分类 {_category_label(next_category)} | 第 {next_page} 页")

        # Notify (non-Telegram)
        try:
            notifier = load_notifier(cfg.get("notify"))
            notifier.notify_batch(new_items, cfg, set())
        except Exception as ne:
            cron_state.warn(f"通知发送失败: {ne}")

        return {
            "skip": False,
            "count": len(items),
            "saved": saved,
            "inserted": inserted,
            "interval": interval,
        }

    except concurrent.futures.TimeoutError:
        error = f"扫描超时（>{_SCAN_TIMEOUT_SECONDS}秒）"
        cron_state.error(error)
        send_admin_telegram_alert(f"系统告警\n类型: 扫描超时\n详情: {error}", cfg)
        if login_username:
            try:
                mark_bili_session_result(login_username, error)
            except Exception:
                pass
        return {
            "skip": False,
            "count": 0,
            "saved": 0,
            "inserted": 0,
            "error": error,
            "interval": interval,
        }
    except ScanRateLimitedError as e:
        cron_state.error(f"扫描出错: {e}")
        send_admin_telegram_alert(f"系统告警\n类型: 扫描频率过高\n详情: {e}", cfg)
        if login_username:
            try:
                mark_bili_session_result(login_username, str(e))
            except Exception:
                pass
        return {
            "skip": False,
            "count": 0,
            "saved": 0,
            "inserted": 0,
            "error": str(e),
            "interval": interval,
        }
    except Exception as e:
        cron_state.error(f"扫描出错: {e}")
        send_admin_telegram_alert(f"系统告警\n类型: 扫描异常\n详情: {e}", cfg)
        if login_username:
            try:
                mark_bili_session_result(login_username, str(e))
            except Exception:
                pass
        return {
            "skip": False,
            "count": 0,
            "saved": 0,
            "inserted": 0,
            "error": str(e),
            "interval": interval,
        }


async def cron_loop() -> None:
    """Async cron loop — runs forever until cancelled."""
    global _CRON_LOOP, _SCAN_NOW_EVENT

    cron_state.is_running = True
    _CRON_LOOP = asyncio.get_running_loop()
    _SCAN_NOW_EVENT = asyncio.Event()
    cron_state.info("后台扫描任务已启动")

    while True:
        cron_state.set_next_scan_in(None)
        try:
            result = await _CRON_LOOP.run_in_executor(None, _run_scan_once)
        except asyncio.CancelledError:
            break
        except Exception as e:
            cron_state.error(f"未预期错误: {e}")
            try:
                from bsm.notify import send_admin_telegram_alert
                send_admin_telegram_alert(f"系统告警\n类型: 后台任务异常\n详情: {e}")
            except Exception:
                pass
            result = {"skip": False, "count": 0, "saved": 0,
                      "inserted": 0, "error": str(e), "interval": 20}

        if not result.get("skip"):
            cron_state.update_scan(
                count=result.get("count", 0),
                saved=result.get("saved", 0),
                inserted=result.get("inserted", 0),
                error=result.get("error"),
            )

        interval = float(result.get("interval", 20))
        cron_state.info(f"等待 {int(interval)} 秒")

        try:
            deadline = _CRON_LOOP.time() + interval
            while True:
                remaining = deadline - _CRON_LOOP.time()
                if remaining <= 0:
                    break
                cron_state.set_next_scan_in(remaining)
                try:
                    await asyncio.wait_for(_SCAN_NOW_EVENT.wait(), timeout=min(1.0, remaining))
                    _SCAN_NOW_EVENT.clear()
                    cron_state.set_next_scan_in(0)
                    break
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            break

    cron_state.is_running = False
    _CRON_LOOP = None
    _SCAN_NOW_EVENT = None
    cron_state.info("后台扫描任务已停止")
