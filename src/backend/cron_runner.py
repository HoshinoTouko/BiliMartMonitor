"""
Cron background task — scan loop without Telegram.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SRC_ROOT = str(Path(__file__).resolve().parent.parent / "src")
if _SRC_ROOT not in sys.path:
    sys.path.insert(0, _SRC_ROOT)

from backend.cron_state import cron_state  # noqa: E402
 
_CONTINUE_MAX_PAGES = 50
_CUR_MAX_PAGES = 50
_SCAN_TIMEOUT_SECONDS = 15
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
_FINALIZE_RESULT_QUEUE: asyncio.Queue[dict[str, object]] | None = None
_FINALIZE_TASKS: set[asyncio.Task[None]] = set()
_BLOB_WRITE_TASKS: set[asyncio.Task[None]] = set()
_BLOB_WRITE_SEMAPHORE: asyncio.Semaphore | None = None
_BLOB_WRITE_MAX_CONCURRENCY = 10
_BLOB_ALERT_THRESHOLD = 8
_BLOB_ALERT_ACTIVE = False
_BLOB_RUNNING_COUNT = 0
_SCAN_PROGRESS_LOADED = False
_SESSION_CACHE_LOADED = False
_SESSION_CACHE: dict[str, dict[str, object]] = {}
_WAIT_PREFIX = "[WAIT]"
_EXEC_PREFIX = "[EXEC]"


def _log_wait(msg: str, level: str = "info") -> None:
    if level == "error":
        cron_state.error(f"{_WAIT_PREFIX} {msg}")
    elif level == "warn":
        cron_state.warn(f"{_WAIT_PREFIX} {msg}")
    else:
        cron_state.info(f"{_WAIT_PREFIX} {msg}")


def _log_exec(msg: str, level: str = "info") -> None:
    if level == "error":
        cron_state.error(f"{_EXEC_PREFIX} {msg}")
    elif level == "warn":
        cron_state.warn(f"{_EXEC_PREFIX} {msg}")
    else:
        cron_state.info(f"{_EXEC_PREFIX} {msg}")


def _mode_log_label(mode: str) -> str:
    if mode == "continue_until_repeat":
        return "CUR"
    return mode


def _new_trace_id() -> str:
    return uuid.uuid4().hex[:8]


def _cleanup_blob_write_tasks() -> None:
    global _BLOB_ALERT_ACTIVE
    done_tasks = [task for task in _BLOB_WRITE_TASKS if task.done()]
    for task in done_tasks:
        _BLOB_WRITE_TASKS.discard(task)
        try:
            exc = task.exception()
        except Exception:
            exc = None
        if exc is not None:
            _log_exec(f"BLOB后台写入任务异常: {exc}", level="error")
    if _BLOB_RUNNING_COUNT < _BLOB_ALERT_THRESHOLD:
        _BLOB_ALERT_ACTIVE = False


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


def _collect_finalize_results(
    queue: asyncio.Queue[dict[str, object]] | None,
) -> list[dict[str, object]]:
    if queue is None:
        return []
    results: list[dict[str, object]] = []
    while True:
        try:
            results.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            break
    return results


def request_scan_now() -> bool:
    if not cron_state.is_running:
        return False
    if _CRON_LOOP is None or _SCAN_NOW_EVENT is None:
        return False
    _CRON_LOOP.call_soon_threadsafe(_SCAN_NOW_EVENT.set)
    _log_wait("已手动触发下一次扫描")
    return True


def reset_scan_progress() -> None:
    global _SCAN_CATEGORY_INDEX

    _SCAN_CATEGORY_INDEX = 0
    _CATEGORY_SCAN_STATE.clear()
    _CATEGORY_SESSION_BINDINGS.clear()
    _CATEGORY_SLEEP_STATE.clear()
    _save_scan_progress()
    _log_wait("扫描进度已重置")


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


def _is_session_failure_error(error: str) -> bool:
    text = str(error or "").strip().lower()
    if not text:
        return False
    keywords = (
        "session",
        "cookie",
        "login",
        "鉴权",
        "未登录",
        "失效",
        "过期",
        "风控",
        "rate",
        "429",
    )
    return any(keyword in text for keyword in keywords)


def _session_username(session: dict[str, object]) -> str:
    return str(session.get("login_username") or "").strip()


def _clone_session(session: dict[str, object]) -> dict[str, object]:
    return dict(session)


def _set_session_cache(raw_sessions: list[dict]) -> None:
    global _SESSION_CACHE, _SESSION_CACHE_LOADED
    cache: dict[str, dict[str, object]] = {}
    for session in raw_sessions:
        if not isinstance(session, dict):
            continue
        username = _session_username(session)
        if not username:
            continue
        cache[username] = _clone_session(session)
    _SESSION_CACHE = cache
    _SESSION_CACHE_LOADED = True


def _load_session_cache(fetch_sessions: callable) -> list[dict[str, object]]:
    global _SESSION_CACHE_LOADED
    if not _SESSION_CACHE_LOADED:
        _set_session_cache(fetch_sessions(status="active"))
    return [_clone_session(session) for session in _SESSION_CACHE.values()]


def _refresh_session_cache(fetch_sessions: callable) -> list[dict[str, object]]:
    _set_session_cache(fetch_sessions(status="active"))
    return [_clone_session(session) for session in _SESSION_CACHE.values()]


def _update_cached_session_scan_result(username: str, *, error: str | None, fetched_count: int = 0) -> None:
    key = str(username or "").strip()
    if not key:
        return
    cached = _SESSION_CACHE.get(key)
    if cached is None:
        return
    now_text = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cached["last_checked_at"] = now_text
    cached["updated_at"] = now_text
    if error is None:
        cached["last_error"] = None
        cached["last_success_fetch_at"] = now_text
        try:
            base_count = int(cached.get("fetch_count") or 0)
        except Exception:
            base_count = 0
        cached["fetch_count"] = max(0, base_count + max(0, int(fetched_count or 0)))
    else:
        cached["last_error"] = str(error)


def _reset_session_cache() -> None:
    global _SESSION_CACHE_LOADED, _SESSION_CACHE
    _SESSION_CACHE_LOADED = False
    _SESSION_CACHE = {}


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


async def _run_scan_once(defer_db_finalize: bool = False) -> dict[str, object]:
    """Run one scan round. API stage runs first; DB stage can be deferred."""
    global _BLOB_WRITE_SEMAPHORE, _BLOB_ALERT_ACTIVE, _BLOB_RUNNING_COUNT
    from bsm.settings import load_runtime_config
    from bsm.db import (
        list_bili_sessions,
        save_items_data_phase,
        flush_pending_blob_updates,
        record_bili_session_scan_success,
        mark_bili_session_result,
    )
    from bsm.scan import scan_once, scan_once_async, ScanRateLimitedError
    from bsm.notify import load_notifier, send_admin_telegram_alert

    _cleanup_blob_write_tasks()
    if _BLOB_WRITE_SEMAPHORE is None:
        _BLOB_WRITE_SEMAPHORE = asyncio.Semaphore(_BLOB_WRITE_MAX_CONCURRENCY)

    cfg = await asyncio.to_thread(load_runtime_config)
    interval = float(cfg.get("interval", 20) or 20)
    api_request_mode = str(cfg.get("api_request_mode", "async") or "async").strip().lower()
    if api_request_mode not in {"sync", "async"}:
        api_request_mode = "async"
    scan_timeout_seconds = float(cfg.get("scan_timeout_seconds", _SCAN_TIMEOUT_SECONDS) or _SCAN_TIMEOUT_SECONDS)
    if scan_timeout_seconds <= 0:
        scan_timeout_seconds = float(_SCAN_TIMEOUT_SECONDS)
    admin_scan_summary_interval_seconds = int(
        cfg.get("admin_scan_summary_interval_seconds", _ADMIN_SCAN_SUMMARY_INTERVAL_SECONDS)
        or _ADMIN_SCAN_SUMMARY_INTERVAL_SECONDS
    )
    if admin_scan_summary_interval_seconds <= 0:
        admin_scan_summary_interval_seconds = int(_ADMIN_SCAN_SUMMARY_INTERVAL_SECONDS)

    mode = cfg.get("scan_mode", "latest")
    categories = _normalize_categories(cfg.get("category"))
    _load_scan_progress()
    cooldown_seconds = int(cfg.get("bili_session_cooldown_seconds", 60) or 60)
    raw_sessions = await asyncio.to_thread(_load_session_cache, list_bili_sessions)
    available_sessions = [session for session in raw_sessions if _is_session_available(session, cooldown_seconds)]
    if not available_sessions:
        raw_sessions = await asyncio.to_thread(_refresh_session_cache, list_bili_sessions)
        available_sessions = [session for session in raw_sessions if _is_session_available(session, cooldown_seconds)]
    if not available_sessions:
        _log_wait("跳过：无可用 session，请先登录", level="warn")
        return {
            "skip": True,
            "interval": interval,
            "admin_scan_summary_interval_seconds": admin_scan_summary_interval_seconds,
        }

    active_categories: list[str | None] = []
    for category in categories:
        if _should_scan_category_this_round(category):
            active_categories.append(category)
        else:
            remaining = _category_sleep_entry(category).get("remaining", 0)
            _log_wait(f"分类 {_category_label(category)} 休眠中，剩余 {remaining} 轮")

    if not active_categories:
        return {
            "skip": True,
            "interval": interval,
            "admin_scan_summary_interval_seconds": admin_scan_summary_interval_seconds,
        }

    assignments = _assign_sessions_to_categories(active_categories, available_sessions)
    assignment_jobs: list[tuple[str | None, dict, str]] = []
    mode_label = _mode_log_label(mode)
    for category, sess in assignments:
        trace_id = _new_trace_id()
        assignment_jobs.append((category, sess, trace_id))
        page = _mode_page(mode, category)
        _log_exec(
            f"开始扫描 | 账号 {str(sess.get('login_username') or '未知')} | 分类 {_category_label(category)} | 模式 {mode_label} | 第 {page} 页 | 追踪ID {trace_id}"
        )

    async def _finalize_scan_round(category_jobs: list[dict[str, object]]) -> dict[str, object]:
        db_results: dict[tuple[str | None, int], dict[str, object]] = {}
        db_tasks: list[asyncio.Task[tuple[tuple[str | None, int], dict[str, object]]]] = []

        async def _run_db_pipeline_for_job(job: dict[str, object]) -> tuple[tuple[str | None, int], dict[str, object]]:
            category = job.get("category")
            page = int(job.get("page") or 0)
            items = list(job.get("items") or [])
            if not items:
                return (category, page), {
                    "new_items": [],
                    "saved": 0,
                    "inserted": 0,
                    "db_duration_ms": 0,
                    "blob_write_count": 0,
                    "pending_blob_updates": [],
                    "blob_backend_name": "",
                    "blob_is_cloudflare": False,
                }

            def _run_db_pipeline() -> dict[str, object]:
                save_result = save_items_data_phase(items)
                return {
                    "new_items": list(save_result.get("new_items") or []),
                    "saved": int(save_result.get("saved") or 0),
                    "inserted": int(save_result.get("inserted") or 0),
                    "db_duration_ms": int(save_result.get("data_write_ms") or 0),
                    "blob_write_count": int(save_result.get("blob_write_count") or 0),
                    "pending_blob_updates": list(save_result.get("pending_blob_updates") or []),
                    "blob_backend_name": str(save_result.get("backend_name") or ""),
                    "blob_is_cloudflare": bool(save_result.get("is_cloudflare") is True),
                }

            result = await asyncio.to_thread(_run_db_pipeline)
            return (category, page), result

        for job in category_jobs:
            if str(job.get("error") or "").strip():
                continue
            db_tasks.append(asyncio.create_task(_run_db_pipeline_for_job(job)))

        if db_tasks:
            for key, result in await asyncio.gather(*db_tasks):
                db_results[key] = result

        total_count = 0
        total_saved = 0
        total_inserted = 0
        any_error: str | None = None
        summary_rows: list[dict[str, object]] = []
        notify_items: list[dict] = []
        session_success_count: dict[str, int] = {}
        session_had_error_before: dict[str, bool] = {}
        session_errors: dict[str, str] = {}
        max_pages = _max_pages_for_mode(mode)
        continue_like_mode = mode in {"continue", "continue_until_repeat"}

        for job in category_jobs:
            category = job["category"]
            page = int(job["page"])
            session = job["session"]
            trace_id = str(job.get("trace_id") or "-")
            username = str(session.get("login_username") or "")
            error = str(job.get("error") or "").strip()
            duration_ms = int(job.get("duration_ms") or 0)
            if error:
                any_error = any_error or error
                session_errors[username] = error
                _log_exec(
                    f"扫描出错 | 账号 {username or '未知'} | 分类 {_category_label(category)} | 耗时 {duration_ms} ms | {error} | 追踪ID {trace_id}",
                    level="error",
                )
                await asyncio.to_thread(
                    send_admin_telegram_alert,
                    f"系统告警\n类型: 扫描异常\n账号: {username or '未知'}\n分类: {_category_label(category)}\n追踪ID: {trace_id}\n详情: {error}",
                    cfg,
                )
                continue

            items = list(job.get("items") or [])
            next_id = job.get("next_id")
            db_result = db_results.get((category, page)) or {}
            new_items = list(db_result.get("new_items") or [])
            saved = int(db_result.get("saved") or 0)
            inserted = int(db_result.get("inserted") or 0)
            db_duration_ms = int(db_result.get("db_duration_ms") or 0)
            blob_write_count = int(db_result.get("blob_write_count") or 0)
            total_duration_ms = duration_ms + db_duration_ms
            total_count += len(items)
            total_saved += saved
            total_inserted += inserted
            notify_items.extend(new_items)

            pending_blob_updates = list(db_result.get("pending_blob_updates") or [])
            if pending_blob_updates:
                blob_backend_name = str(db_result.get("blob_backend_name") or "unknown")
                blob_is_cloudflare = bool(db_result.get("blob_is_cloudflare") is True)

                async def _run_blob_write(
                    category_value: str | None,
                    page_value: int,
                    trace_id_value: str,
                    updates: list[tuple[int, bytes, str]],
                    backend_name_value: str,
                    is_cloudflare_value: bool,
                ) -> None:
                    global _BLOB_RUNNING_COUNT, _BLOB_ALERT_ACTIVE
                    assert _BLOB_WRITE_SEMAPHORE is not None
                    async with _BLOB_WRITE_SEMAPHORE:
                        _BLOB_RUNNING_COUNT += 1
                        running_now = _BLOB_RUNNING_COUNT
                        if running_now >= _BLOB_ALERT_THRESHOLD and not _BLOB_ALERT_ACTIVE:
                            _BLOB_ALERT_ACTIVE = True
                            warn_message = (
                                "系统告警\n"
                                "类型: BLOB写入并发预警\n"
                                f"详情: 当前并发任务 {running_now}/{_BLOB_WRITE_MAX_CONCURRENCY}，阈值 {_BLOB_ALERT_THRESHOLD}"
                            )
                            asyncio.create_task(asyncio.to_thread(send_admin_telegram_alert, warn_message, cfg))
                            _log_exec(
                                f"BLOB并发达到告警阈值 | 当前并发任务 {running_now}/{_BLOB_WRITE_MAX_CONCURRENCY}",
                                level="warn",
                            )
                        try:
                            blob_result = await asyncio.to_thread(
                                flush_pending_blob_updates,
                                updates,
                                is_cloudflare=is_cloudflare_value,
                                backend_name=backend_name_value,
                            )
                            _log_exec(
                                f"BLOB写入完成 | 分类 {_category_label(category_value)} | 第 {page_value} 页 | 条数 {int(blob_result.get('blob_write_count') or 0)} | 耗时 {int(blob_result.get('blob_write_ms') or 0)} ms | 追踪ID {trace_id_value}"
                            )
                        finally:
                            _BLOB_RUNNING_COUNT = max(0, _BLOB_RUNNING_COUNT - 1)

                blob_task = asyncio.create_task(
                    _run_blob_write(
                        category,
                        page,
                        trace_id,
                        pending_blob_updates,
                        blob_backend_name,
                        blob_is_cloudflare,
                    )
                )
                _BLOB_WRITE_TASKS.add(blob_task)
                blob_task.add_done_callback(lambda t: _BLOB_WRITE_TASKS.discard(t))
                blob_queued = len(_BLOB_WRITE_TASKS)
                _log_exec(
                    f"BLOB写入已排队 | 分类 {_category_label(category)} | 第 {page} 页 | 条数 {blob_write_count} | 队列任务 {blob_queued} | 运行并发 {_BLOB_RUNNING_COUNT}/{_BLOB_WRITE_MAX_CONCURRENCY} | 追踪ID {trace_id}"
                )

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
                _log_wait(f"分类 {_category_label(category)} 第1页命中重复，休眠 {sleep_level} 轮")

            summary_rows.append({
                "category_key": _category_key(category),
                "category_label": _category_label(category),
                "count": len(items),
                "inserted": inserted,
                "did_reset_cursor": did_reset_cursor,
                "duration_ms": total_duration_ms,
                "request_duration_ms": duration_ms,
                "db_duration_ms": db_duration_ms,
                "blob_write_count": blob_write_count,
                "trace_id": trace_id,
            })
            _log_exec(
                f"扫描完成 | 分类 {_category_label(category)} | 模式 {mode_label} | 第 {page} 页 | {len(items)} 条 | 新增 {inserted} 条 | 耗时 API {duration_ms} ms | DB {db_duration_ms} ms | 追踪ID {trace_id}"
            )
            _log_wait(f"下次扫描 | 分类 {_category_label(category)} | 第 {_mode_page(mode, category)} 页 | 追踪ID {trace_id}")
            if username and username not in session_errors:
                session_success_count[username] = session_success_count.get(username, 0) + len(items)
                if username not in session_had_error_before:
                    session_had_error_before[username] = bool(str(session.get("last_error") or "").strip())

        _save_scan_progress()

        for username, fetched_count in session_success_count.items():
            if username in session_errors:
                continue
            if int(fetched_count or 0) <= 0 and not session_had_error_before.get(username, False):
                continue
            await asyncio.to_thread(record_bili_session_scan_success, username, fetched_count=fetched_count)
            _update_cached_session_scan_result(username, error=None, fetched_count=int(fetched_count or 0))
        for username, error in session_errors.items():
            if username:
                await asyncio.to_thread(mark_bili_session_result, username, error)
                _update_cached_session_scan_result(username, error=error)
        if any(_is_session_failure_error(err) for err in session_errors.values()):
            await asyncio.to_thread(_refresh_session_cache, list_bili_sessions)

        try:
            notifier = await asyncio.to_thread(load_notifier, cfg.get("notify"))
            await asyncio.to_thread(notifier.notify_batch, notify_items, cfg, set())
        except Exception as ne:
            _log_exec(f"通知发送失败: {ne}", level="warn")

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

    try:
        async def _run_scan_job(category: str | None, sess: dict, trace_id: str) -> dict[str, object]:
            state = _get_category_state(category)
            scan_next_id = state["next_id"] if mode in {"continue", "continue_until_repeat"} else None
            scan_cfg = dict(cfg)
            scan_cfg["category"] = category or ""
            scan_cfg["scan_timeout_seconds"] = scan_timeout_seconds
            started_at = time.perf_counter()
            meta: dict[str, object] = {
                "category": category,
                "session": sess,
                "page": _mode_page(mode, category),
                "next_id": None,
                "items": [],
                "error": None,
                "trace_id": trace_id,
            }
            try:
                if api_request_mode == "sync":
                    scan_coro = asyncio.to_thread(scan_once, str(sess.get("cookies") or ""), scan_cfg, scan_next_id)
                else:
                    scan_coro = scan_once_async(str(sess.get("cookies") or ""), scan_cfg, scan_next_id)
                next_id, items = await asyncio.wait_for(scan_coro, timeout=scan_timeout_seconds)
                meta["next_id"] = next_id
                meta["items"] = items if isinstance(items, list) else []
            except asyncio.TimeoutError:
                meta["error"] = f"扫描超时（>{scan_timeout_seconds}秒）"
            except ScanRateLimitedError as e:
                meta["error"] = str(e)
            except Exception as e:
                meta["error"] = str(e)
            meta["duration_ms"] = int((time.perf_counter() - started_at) * 1000)
            return meta

        scan_tasks = [asyncio.create_task(_run_scan_job(category, sess, trace_id)) for category, sess, trace_id in assignment_jobs]
        category_jobs = await asyncio.gather(*scan_tasks)

        if defer_db_finalize:
            async def _finalize_and_publish() -> None:
                result = await _finalize_scan_round(category_jobs)
                if _FINALIZE_RESULT_QUEUE is not None:
                    await _FINALIZE_RESULT_QUEUE.put(result)

            task = asyncio.create_task(_finalize_and_publish())
            _FINALIZE_TASKS.add(task)
            task.add_done_callback(lambda t: _FINALIZE_TASKS.discard(t))
            return {
                "skip": False,
                "deferred": True,
                "interval": interval,
                "admin_scan_summary_interval_seconds": admin_scan_summary_interval_seconds,
            }

        return await _finalize_scan_round(category_jobs)
    except Exception as e:
        _log_exec(f"扫描出错: {e}", level="error")
        await asyncio.to_thread(send_admin_telegram_alert, f"系统告警\n类型: 扫描异常\n详情: {e}", cfg)
        return {
            "skip": False,
            "count": 0,
            "saved": 0,
            "inserted": 0,
            "error": str(e),
            "interval": interval,
            "admin_scan_summary_interval_seconds": admin_scan_summary_interval_seconds,
        }


def _apply_scan_result(
    result: dict[str, object],
    bucket: dict[str, dict[str, int | str]],
) -> None:
    if result.get("skip") or result.get("deferred"):
        return
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
                _accumulate_admin_scan_summary(bucket, row)


async def cron_loop() -> None:
    """Async cron loop — runs forever until cancelled."""
    global _CRON_LOOP, _SCAN_NOW_EVENT, _FINALIZE_RESULT_QUEUE, _BLOB_WRITE_SEMAPHORE, _BLOB_ALERT_ACTIVE, _BLOB_RUNNING_COUNT

    cron_state.is_running = True
    _CRON_LOOP = asyncio.get_running_loop()
    _SCAN_NOW_EVENT = asyncio.Event()
    _FINALIZE_RESULT_QUEUE = asyncio.Queue()
    _load_scan_progress()
    admin_summary_interval_seconds = _ADMIN_SCAN_SUMMARY_INTERVAL_SECONDS
    next_admin_summary_at = _CRON_LOOP.time() + admin_summary_interval_seconds
    admin_summary_bucket: dict[str, dict[str, int | str]] = {}
    _log_wait("后台扫描任务已启动")

    while True:
        for finalized in _collect_finalize_results(_FINALIZE_RESULT_QUEUE):
            _apply_scan_result(finalized, admin_summary_bucket)

        cron_state.set_next_scan_in(None)
        dispatch_started_at = _CRON_LOOP.time()
        try:
            result = await _run_scan_once()
        except asyncio.CancelledError:
            break
        except Exception as e:
            _log_exec(f"未预期错误: {e}", level="error")
            try:
                from bsm.notify import send_admin_telegram_alert
                await asyncio.to_thread(send_admin_telegram_alert, f"系统告警\n类型: 后台任务异常\n详情: {e}")
            except Exception:
                pass
            result = {"skip": False, "count": 0, "saved": 0,
                      "inserted": 0, "error": str(e), "interval": 20, "admin_scan_summary_interval_seconds": int(admin_summary_interval_seconds)}
        _apply_scan_result(result, admin_summary_bucket)

        now = _CRON_LOOP.time()
        configured_admin_interval = float(result.get("admin_scan_summary_interval_seconds", admin_summary_interval_seconds) or admin_summary_interval_seconds)
        if configured_admin_interval <= 0:
            configured_admin_interval = _ADMIN_SCAN_SUMMARY_INTERVAL_SECONDS
        if configured_admin_interval != admin_summary_interval_seconds:
            admin_summary_interval_seconds = configured_admin_interval
            next_admin_summary_at = now + admin_summary_interval_seconds
            admin_summary_bucket.clear()
            _log_wait(f"管理员扫描汇总推送周期已更新为 {int(admin_summary_interval_seconds)} 秒")
        if now >= next_admin_summary_at:
            from bsm.notify import send_admin_telegram_alert

            summary_message = _build_admin_scan_summary_message(admin_summary_bucket)
            sent = await asyncio.to_thread(send_admin_telegram_alert, summary_message)
            _log_wait(f"10分钟扫描汇总已推送（{sent}）")
            admin_summary_bucket.clear()
            while next_admin_summary_at <= now:
                next_admin_summary_at += admin_summary_interval_seconds

        interval = float(result.get("interval", 20) or 20)
        _log_wait(f"等待 {int(interval)} 秒")

        try:
            deadline = dispatch_started_at + interval
            while True:
                for finalized in _collect_finalize_results(_FINALIZE_RESULT_QUEUE):
                    _apply_scan_result(finalized, admin_summary_bucket)
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

    if _FINALIZE_TASKS:
        await asyncio.gather(*list(_FINALIZE_TASKS), return_exceptions=True)
    if _BLOB_WRITE_TASKS:
        await asyncio.gather(*list(_BLOB_WRITE_TASKS), return_exceptions=True)
    for finalized in _collect_finalize_results(_FINALIZE_RESULT_QUEUE):
        _apply_scan_result(finalized, admin_summary_bucket)

    cron_state.is_running = False
    _CRON_LOOP = None
    _SCAN_NOW_EVENT = None
    _FINALIZE_RESULT_QUEUE = None
    _BLOB_WRITE_SEMAPHORE = None
    _BLOB_ALERT_ACTIVE = False
    _BLOB_RUNNING_COUNT = 0
    _reset_session_cache()
    _log_wait("后台扫描任务已停止")
