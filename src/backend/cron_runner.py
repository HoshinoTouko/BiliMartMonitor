"""
Cron background task — scan loop without Telegram.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SRC_ROOT = str(Path(__file__).resolve().parent.parent / "src")
if _SRC_ROOT not in sys.path:
    sys.path.insert(0, _SRC_ROOT)

from backend.cron_state import cron_state  # noqa: E402

_CONTINUE_MAX_PAGES = 50
_CUR_MAX_PAGES = 50
_SCAN_TIMEOUT_SECONDS = 30
_ADMIN_SCAN_SUMMARY_INTERVAL_SECONDS = 600.0
_SCAN_CATEGORY_INDEX = 0
_CATEGORY_SCAN_STATE: dict[str, dict[str, int | str | None]] = {}
_CATEGORY_SESSION_BINDINGS: dict[str, str] = {}
_CATEGORY_SLEEP_STATE: dict[str, dict[str, int]] = {}
_CATEGORY_LABELS = {
    "2312": "手办",
    "2066": "模型",
    "2331": "周边",
    "2273": "3C",
    "fudai_cate_id": "福袋",
}
_SCAN_NOW_EVENT: asyncio.Event | None = None
_CRON_LOOP: asyncio.AbstractEventLoop | None = None
_SCAN_PROGRESS_LOADED = False


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


def _category_order_key(category_key: str) -> tuple[int, str]:
    if category_key in _CATEGORY_LABELS:
        return (list(_CATEGORY_LABELS.keys()).index(category_key), category_key)
    if category_key == "":
        return (len(_CATEGORY_LABELS), category_key)
    return (len(_CATEGORY_LABELS) + 1, category_key)


def _accumulate_admin_scan_summary(
    bucket: dict[str, dict[str, int | str]],
    result: dict,
) -> None:
    category_key = str(result.get("category_key") or "")
    category_label = str(result.get("category_label") or _category_label(category_key or None))
    total = int(result.get("count", 0) or 0)
    inserted = int(result.get("inserted", 0) or 0)
    resets = 1 if bool(result.get("did_reset_cursor")) else 0
    if total <= 0 and inserted <= 0 and resets <= 0:
        return
    current = bucket.setdefault(category_key, {"label": category_label, "inserted": 0, "resets": 0, "total": 0})
    current["inserted"] = int(current.get("inserted", 0) or 0) + inserted
    current["resets"] = int(current.get("resets", 0) or 0) + resets
    current["total"] = int(current.get("total", 0) or 0) + total


def _build_admin_scan_summary_message(bucket: dict[str, dict[str, int | str]]) -> str:
    lines = ["10分钟新增"]
    if not bucket:
        lines.append("暂无扫描数据")
        return "\n".join(lines)
    for category_key in sorted(bucket.keys(), key=_category_order_key):
        summary = bucket[category_key]
        label = str(summary.get("label") or _category_label(category_key or None))
        inserted = int(summary.get("inserted", 0) or 0)
        resets = int(summary.get("resets", 0) or 0)
        total = int(summary.get("total", 0) or 0)
        lines.append(f"{label} {inserted} 条 | 重置 {resets} 次 | 合计 {total} 条")
    return "\n".join(lines)


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


def _scan_progress_path() -> str:
    from bsm.env import data_dir

    return os.path.join(data_dir(), "scan_progress.json")


def _save_scan_progress() -> None:
    payload: dict[str, object] = {
        "scan_category_index": int(_SCAN_CATEGORY_INDEX),
        "category_scan_state": {},
    }
    serialized_state: dict[str, dict[str, int | str | None]] = {}
    for category_key, state in _CATEGORY_SCAN_STATE.items():
        next_id = state.get("next_id")
        page_count = int(state.get("page_count", 0) or 0)
        if next_id is None and page_count <= 0:
            continue
        serialized_state[category_key] = {
            "next_id": str(next_id) if next_id is not None else None,
            "page_count": page_count,
        }
    payload["category_scan_state"] = serialized_state

    path = _scan_progress_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except Exception:
        pass


def _load_scan_progress(force: bool = False) -> None:
    global _SCAN_PROGRESS_LOADED, _SCAN_CATEGORY_INDEX

    if _SCAN_PROGRESS_LOADED and not force:
        return
    _SCAN_PROGRESS_LOADED = True

    path = _scan_progress_path()
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return
    if not isinstance(raw, dict):
        return

    try:
        _SCAN_CATEGORY_INDEX = max(0, int(raw.get("scan_category_index", 0) or 0))
    except Exception:
        _SCAN_CATEGORY_INDEX = 0

    category_scan_state = raw.get("category_scan_state")
    if not isinstance(category_scan_state, dict):
        return
    _CATEGORY_SCAN_STATE.clear()
    for category_key, state in category_scan_state.items():
        if not isinstance(state, dict):
            continue
        next_id = state.get("next_id")
        try:
            page_count = max(0, int(state.get("page_count", 0) or 0))
        except Exception:
            page_count = 0
        if next_id is None and page_count <= 0:
            continue
        _CATEGORY_SCAN_STATE[str(category_key)] = {
            "next_id": str(next_id) if next_id is not None else None,
            "page_count": page_count,
        }


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
    _CATEGORY_SESSION_BINDINGS.clear()
    _CATEGORY_SLEEP_STATE.clear()
    _save_scan_progress()
    cron_state.info("扫描进度已重置")


def _category_sleep_entry(category: str | None) -> dict[str, int]:
    return _CATEGORY_SLEEP_STATE.setdefault(_category_key(category), {"level": 0, "remaining": 0})


def _should_scan_category_this_round(category: str | None) -> bool:
    entry = _category_sleep_entry(category)
    remaining = int(entry.get("remaining", 0) or 0)
    if remaining > 0:
        entry["remaining"] = remaining - 1
        return False
    return True


def _update_category_sleep_state(category: str | None, first_page_repeat: bool) -> int:
    entry = _category_sleep_entry(category)
    if first_page_repeat:
        next_level = min(int(entry.get("level", 0) or 0) + 1, 6)
        entry["level"] = next_level
        entry["remaining"] = next_level
        return next_level
    entry["level"] = 0
    entry["remaining"] = 0
    return 0


def _parse_utc_timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _is_session_available(session: dict, cooldown_seconds: int) -> bool:
    if str(session.get("status") or "active") != "active":
        return False
    if not str(session.get("cookies") or "").strip():
        return False
    if cooldown_seconds <= 0:
        return True
    if not str(session.get("last_error") or "").strip():
        return True
    checked_at = _parse_utc_timestamp(session.get("last_checked_at"))
    if checked_at is None:
        return True
    return checked_at <= (datetime.now(timezone.utc) - timedelta(seconds=cooldown_seconds))


def _assign_sessions_to_categories(
    categories: list[str | None],
    sessions: list[dict],
) -> list[tuple[str | None, dict]]:
    global _CATEGORY_SESSION_BINDINGS

    session_by_username = {
        str(session.get("login_username") or "").strip(): session
        for session in sessions
        if str(session.get("login_username") or "").strip()
    }
    valid_usernames = set(session_by_username.keys())
    _CATEGORY_SESSION_BINDINGS = {
        key: username
        for key, username in _CATEGORY_SESSION_BINDINGS.items()
        if username in valid_usernames
    }

    assignments: list[tuple[str | None, dict]] = []
    load_count: dict[str, int] = {username: 0 for username in valid_usernames}

    for category in categories:
        category_key = _category_key(category)
        bound_username = _CATEGORY_SESSION_BINDINGS.get(category_key)
        if bound_username and bound_username in session_by_username:
            load_count[bound_username] = load_count.get(bound_username, 0) + 1
            assignments.append((category, session_by_username[bound_username]))
            continue

        chosen = min(
            sessions,
            key=lambda s: (
                load_count.get(str(s.get("login_username") or ""), 0),
                str(s.get("login_username") or ""),
            ),
        )
        chosen_username = str(chosen.get("login_username") or "")
        _CATEGORY_SESSION_BINDINGS[category_key] = chosen_username
        load_count[chosen_username] = load_count.get(chosen_username, 0) + 1
        assignments.append((category, chosen))
    return assignments


def _run_scan_once() -> dict:
    """Blocking scan — runs in a thread executor (bsm code is synchronous)."""
    from bsm.settings import load_runtime_config
    from bsm.db import (
        filter_new_items,
        list_bili_sessions,
        save_items,
        record_bili_session_fetch_success,
        mark_bili_session_result,
    )
    from bsm.scan import scan_once, ScanRateLimitedError
    from bsm.notify import load_notifier, send_admin_telegram_alert

    cfg = load_runtime_config()
    interval = cfg.get("interval", 20)
    admin_scan_summary_interval_seconds = int(cfg.get("admin_scan_summary_interval_seconds", _ADMIN_SCAN_SUMMARY_INTERVAL_SECONDS) or _ADMIN_SCAN_SUMMARY_INTERVAL_SECONDS)
    if admin_scan_summary_interval_seconds <= 0:
        admin_scan_summary_interval_seconds = int(_ADMIN_SCAN_SUMMARY_INTERVAL_SECONDS)

    mode = cfg.get("scan_mode", "latest")
    categories = _normalize_categories(cfg.get("category"))
    _load_scan_progress()
    cooldown_seconds = int(cfg.get("bili_session_cooldown_seconds", 60) or 60)
    raw_sessions = list_bili_sessions(status="active")
    available_sessions = [session for session in raw_sessions if _is_session_available(session, cooldown_seconds)]
    if not available_sessions:
        cron_state.warn("跳过：无可用 session，请先登录")
        return {"skip": True, "interval": interval, "admin_scan_summary_interval_seconds": admin_scan_summary_interval_seconds}

    active_categories: list[str | None] = []
    for category in categories:
        if _should_scan_category_this_round(category):
            active_categories.append(category)
        else:
            remaining = _category_sleep_entry(category).get("remaining", 0)
            cron_state.info(f"分类 {_category_label(category)} 休眠中，剩余 {remaining} 轮")

    if not active_categories:
        return {"skip": True, "interval": interval, "admin_scan_summary_interval_seconds": admin_scan_summary_interval_seconds}

    assignments = _assign_sessions_to_categories(active_categories, available_sessions)
    mode_label = _mode_log_label(mode)
    for category, sess in assignments:
        page = _mode_page(mode, category)
        cron_state.info(
            f"开始扫描 | 账号 {str(sess.get('login_username') or '未知')} | 分类 {_category_label(category)} | 模式 {mode_label} | 第 {page} 页"
        )

    try:
        continue_like_mode = mode in {"continue", "continue_until_repeat"}
        category_jobs: list[dict] = []
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(assignments)))
        try:
            future_map = {}
            for category, sess in assignments:
                state = _get_category_state(category)
                scan_next_id = state["next_id"] if continue_like_mode else None
                scan_cfg = dict(cfg)
                scan_cfg["category"] = category or ""
                scan_cfg["scan_timeout_seconds"] = _SCAN_TIMEOUT_SECONDS
                future = executor.submit(scan_once, str(sess.get("cookies") or ""), scan_cfg, scan_next_id)
                future_map[future] = {
                    "category": category,
                    "session": sess,
                    "page": _mode_page(mode, category),
                }
            for future, meta in future_map.items():
                try:
                    next_id, items = future.result(timeout=_SCAN_TIMEOUT_SECONDS)
                    meta["next_id"] = next_id
                    meta["items"] = items if isinstance(items, list) else []
                    meta["error"] = None
                except concurrent.futures.TimeoutError:
                    meta["error"] = f"扫描超时（>{_SCAN_TIMEOUT_SECONDS}秒）"
                    meta["items"] = []
                    meta["next_id"] = None
                except ScanRateLimitedError as e:
                    meta["error"] = str(e)
                    meta["items"] = []
                    meta["next_id"] = None
                except Exception as e:
                    meta["error"] = str(e)
                    meta["items"] = []
                    meta["next_id"] = None
                category_jobs.append(meta)
        finally:
            executor.shutdown(wait=True, cancel_futures=True)

        total_count = 0
        total_saved = 0
        total_inserted = 0
        any_error: str | None = None
        summary_rows: list[dict[str, object]] = []
        notify_items: list[dict] = []
        session_success_count: dict[str, int] = {}
        session_errors: dict[str, str] = {}
        max_pages = _max_pages_for_mode(mode)

        for job in category_jobs:
            category = job["category"]
            page = int(job["page"])
            session = job["session"]
            username = str(session.get("login_username") or "")
            error = str(job.get("error") or "").strip()
            if error:
                any_error = any_error or error
                session_errors[username] = error
                cron_state.error(f"扫描出错 | 账号 {username or '未知'} | 分类 {_category_label(category)} | {error}")
                send_admin_telegram_alert(
                    f"系统告警\n类型: 扫描异常\n账号: {username or '未知'}\n分类: {_category_label(category)}\n详情: {error}",
                    cfg,
                )
                continue

            items = list(job.get("items") or [])
            next_id = job.get("next_id")
            new_items = filter_new_items(items)
            saved, inserted = save_items(items)
            total_count += len(items)
            total_saved += int(saved)
            total_inserted += int(inserted)
            notify_items.extend(new_items)

            should_reset_on_repeat = mode == "continue_until_repeat" and len(new_items) < len(items)
            did_reset_cursor = False
            first_page_repeat = page == 1 and len(new_items) < len(items)
            if continue_like_mode:
                active_state = _get_category_state(category)
                next_page_count = int(active_state["page_count"]) + 1
                active_state["page_count"] = next_page_count
                if should_reset_on_repeat or next_id is None or next_page_count >= max_pages:
                    _clear_category_state(category)
                    did_reset_cursor = True
                else:
                    active_state["next_id"] = next_id
            else:
                _clear_category_state(category)

            sleep_level = _update_category_sleep_state(category, first_page_repeat)
            if sleep_level > 0:
                cron_state.info(f"分类 {_category_label(category)} 第1页命中重复，休眠 {sleep_level} 轮")

            summary_rows.append({
                "category_key": _category_key(category),
                "category_label": _category_label(category),
                "count": len(items),
                "inserted": int(inserted),
                "did_reset_cursor": did_reset_cursor,
            })
            cron_state.info(
                f"扫描完成 | 分类 {_category_label(category)} | 模式 {mode_label} | 第 {page} 页 | {len(items)} 条 | 新增 {inserted} 条"
            )
            cron_state.info(f"下次扫描 | 分类 {_category_label(category)} | 第 {_mode_page(mode, category)} 页")
            if username and username not in session_errors:
                session_success_count[username] = session_success_count.get(username, 0) + len(items)

        _save_scan_progress()

        for username, fetched_count in session_success_count.items():
            if username in session_errors:
                continue
            record_bili_session_fetch_success(username, fetched_count=fetched_count)
            mark_bili_session_result(username, None)
        for username, error in session_errors.items():
            if username:
                mark_bili_session_result(username, error)

        # Notify (non-Telegram)
        try:
            notifier = load_notifier(cfg.get("notify"))
            notifier.notify_batch(notify_items, cfg, set())
        except Exception as ne:
            cron_state.warn(f"通知发送失败: {ne}")

        return {
            "skip": False,
            "count": total_count,
            "saved": total_saved,
            "inserted": total_inserted,
            "interval": interval,
            "summary_rows": summary_rows,
            "error": any_error,
            "admin_scan_summary_interval_seconds": admin_scan_summary_interval_seconds,
        }
    except Exception as e:
        cron_state.error(f"扫描出错: {e}")
        send_admin_telegram_alert(f"系统告警\n类型: 扫描异常\n详情: {e}", cfg)
        return {
            "skip": False,
            "count": 0,
            "saved": 0,
            "inserted": 0,
            "error": str(e),
            "interval": interval,
            "admin_scan_summary_interval_seconds": admin_scan_summary_interval_seconds,
        }


async def cron_loop() -> None:
    """Async cron loop — runs forever until cancelled."""
    global _CRON_LOOP, _SCAN_NOW_EVENT

    cron_state.is_running = True
    _CRON_LOOP = asyncio.get_running_loop()
    _SCAN_NOW_EVENT = asyncio.Event()
    _load_scan_progress()
    admin_summary_interval_seconds = _ADMIN_SCAN_SUMMARY_INTERVAL_SECONDS
    next_admin_summary_at = _CRON_LOOP.time() + admin_summary_interval_seconds
    admin_summary_bucket: dict[str, dict[str, int | str]] = {}
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
                      "inserted": 0, "error": str(e), "interval": 20, "admin_scan_summary_interval_seconds": int(admin_summary_interval_seconds)}

        if not result.get("skip"):
            cron_state.update_scan(
                count=result.get("count", 0),
                saved=result.get("saved", 0),
                inserted=result.get("inserted", 0),
                error=result.get("error"),
            )
            summary_rows = result.get("summary_rows") or []
            if isinstance(summary_rows, list):
                for row in summary_rows:
                    if isinstance(row, dict):
                        _accumulate_admin_scan_summary(admin_summary_bucket, row)

        now = _CRON_LOOP.time()
        configured_admin_interval = float(result.get("admin_scan_summary_interval_seconds", admin_summary_interval_seconds) or admin_summary_interval_seconds)
        if configured_admin_interval <= 0:
            configured_admin_interval = _ADMIN_SCAN_SUMMARY_INTERVAL_SECONDS
        if configured_admin_interval != admin_summary_interval_seconds:
            admin_summary_interval_seconds = configured_admin_interval
            next_admin_summary_at = now + admin_summary_interval_seconds
            admin_summary_bucket.clear()
            cron_state.info(f"管理员扫描汇总推送周期已更新为 {int(admin_summary_interval_seconds)} 秒")
        if now >= next_admin_summary_at:
            from bsm.notify import send_admin_telegram_alert

            summary_message = _build_admin_scan_summary_message(admin_summary_bucket)
            sent = send_admin_telegram_alert(summary_message)
            cron_state.info(f"10分钟扫描汇总已推送（{sent}）")
            admin_summary_bucket.clear()
            while next_admin_summary_at <= now:
                next_admin_summary_at += admin_summary_interval_seconds

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
