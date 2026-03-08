"""
Settings router.

Routes:
  GET  /api/settings        → read all runtime settings + cron status
  PUT  /api/settings        → update writable settings
  GET  /api/settings/cron   → cron status only (for polling)
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

_SRC_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _SRC_ROOT not in sys.path:
    sys.path.insert(0, _SRC_ROOT)

from backend.cron_state import cron_state  # noqa: E402
from backend.auth import get_current_user, get_current_admin  # noqa: E402

router = APIRouter()

_ALL_PRICE_FILTERS = ["0-2000", "2000-3000", "3000-5000", "5000-10000", "10000-20000", "20000-0"]
_ALL_DISCOUNT_FILTERS = ["70-100", "50-70", "30-50", "0-30"]


def _unauthorized() -> JSONResponse:
    return JSONResponse({"detail": "authentication required"}, status_code=401)


def _forbidden(message: str = "forbidden") -> JSONResponse:
    return JSONResponse({"detail": message}, status_code=403)


def _can_access_user(actor: Dict[str, Any], username: str) -> bool:
    if not username:
        return False
    actor_username = str(actor.get("username") or "")
    if username == actor_username:
        return True
    return "admin" in (actor.get("roles") or [])


def _normalize_filter_selection(values: Optional[List[str]], all_options: List[str]) -> List[str]:
    if values is None:
        return []
    selected = {str(item).strip() for item in values if str(item).strip()}
    normalized = [option for option in all_options if option in selected]
    if len(normalized) == len(all_options):
        # All selected => store empty list (means no filter limit).
        return []
    return normalized


def _filter_selection_for_response(values: Optional[List[str]], all_options: List[str]) -> List[str]:
    selected = {str(item).strip() for item in (values or []) if str(item).strip()}
    normalized = [option for option in all_options if option in selected]
    # Empty means "all selected" in persisted config.
    return normalized if normalized else list(all_options)


def _load_settings() -> Dict[str, Any]:
    from bsm.settings import load_runtime_config
    from bsm.env import env_str

    cfg = load_runtime_config()
    return {
        "scan_mode": cfg.get("scan_mode", "latest"),
        "interval": cfg.get("interval", 20),
        "category": cfg.get("category", ""),
        "timezone": cfg.get("timezone", "Asia/Shanghai"),
        "app_base_url": cfg.get("app_base_url", ""),
        "cloudflare_validation_enabled": bool(cfg.get("cloudflare_validation_enabled", False)),
        "cloudflare_turnstile_site_key": cfg.get("cloudflare_turnstile_site_key", ""),
        "cloudflare_turnstile_secret_key_configured": bool(cfg.get("cloudflare_turnstile_secret_key", "")),
        "bili_session_pick_mode": cfg.get("bili_session_pick_mode", "round_robin"),
        "bili_session_cooldown_seconds": cfg.get("bili_session_cooldown_seconds", 60),
        "admin_scan_summary_interval_seconds": cfg.get("admin_scan_summary_interval_seconds", 600),
        "admin_telegram_ids": cfg.get("admin_telegram_ids") or [],
        "price_filters": _filter_selection_for_response(cfg.get("price_filters"), _ALL_PRICE_FILTERS),
        "discount_filters": _filter_selection_for_response(cfg.get("discount_filters"), _ALL_DISCOUNT_FILTERS),
        "db_backend": env_str("BSM_DB_BACKEND", "sqlite"),
        "cron": cron_state.to_dict(),
    }


class SettingsUpdate(BaseModel):
    scan_mode: Optional[str] = None
    interval: Optional[int] = None
    category: Optional[str] = None
    timezone: Optional[str] = None
    app_base_url: Optional[str] = None
    cloudflare_validation_enabled: Optional[bool] = None
    cloudflare_turnstile_site_key: Optional[str] = None
    cloudflare_turnstile_secret_key: Optional[str] = None
    bili_session_pick_mode: Optional[str] = None
    bili_session_cooldown_seconds: Optional[int] = None
    admin_scan_summary_interval_seconds: Optional[int] = None
    admin_telegram_ids: Optional[List[str]] = None
    price_filters: Optional[List[str]] = None
    discount_filters: Optional[List[str]] = None


class UserNotificationUpdate(BaseModel):
    username: str
    notify_enabled: Optional[bool] = None
    keywords: Optional[List[str]] = None
    telegram_ids: Optional[List[str]] = None


@router.get("/api/settings")
def api_get_settings(_: Dict[str, Any] = Depends(get_current_admin)) -> JSONResponse:
    return JSONResponse(_load_settings())


@router.get("/api/settings/cron")
def api_get_cron_status(_: Dict[str, Any] = Depends(get_current_admin)) -> JSONResponse:
    return JSONResponse(cron_state.to_dict())


@router.post("/api/settings/cron/trigger")
def api_trigger_cron_scan(_: Dict[str, Any] = Depends(get_current_admin)) -> JSONResponse:
    from backend.cron_runner import request_scan_now

    if not request_scan_now():
        return JSONResponse({"error": "cron is not running"}, status_code=409)
    return JSONResponse({"ok": True})


@router.post("/api/settings/cron/restart")
async def api_restart_cron(_: Dict[str, Any] = Depends(get_current_admin)) -> JSONResponse:
    from backend.main import restart_cron_task

    await restart_cron_task()
    return JSONResponse({"ok": True})


@router.get("/api/account/settings")
def api_get_user_settings(_: Dict[str, Any] = Depends(get_current_user)) -> JSONResponse:
    """Return a subset of public/user-level settings (e.g. refresh interval)."""
    from bsm.settings import get_public_account_settings

    return JSONResponse(get_public_account_settings())


@router.get("/api/public/login-settings")
def api_get_public_login_settings() -> JSONResponse:
    from bsm.settings import get_public_account_settings

    data = get_public_account_settings()
    return JSONResponse({
        "cloudflare_validation_enabled": bool(data.get("cloudflare_validation_enabled", False)),
        "cloudflare_turnstile_site_key": str(data.get("cloudflare_turnstile_site_key") or ""),
    })


@router.get("/api/settings/logs")
def api_get_cron_logs(n: int = 20, _: Dict[str, Any] = Depends(get_current_admin)) -> JSONResponse:
    """Return last N cron log lines (max 200)."""
    lines = cron_state.get_logs(min(n, 200))
    return JSONResponse({"logs": lines})


@router.get("/api/settings/user-notifications")
def api_get_user_notifications(username: str, actor: Dict[str, Any] = Depends(get_current_user)) -> JSONResponse:
    from bsm.settings import get_access_user, get_telegram_bot_id

    username = (username or "").strip()
    if not _can_access_user(actor, username):
        return _forbidden()

    actor_username = str(actor.get("username") or "").strip()
    user = actor if username == actor_username else get_access_user(username)
    if not user:
        return JSONResponse({"error": "user not found"}, status_code=404)
    return JSONResponse({
        "username": user.get("username", ""),
        "notify_enabled": bool(user.get("notify_enabled", True)),
        "keywords": user.get("keywords") or [],
        "telegram_ids": user.get("telegram_ids") or [],
        "bot_id": get_telegram_bot_id(),
    })


@router.put("/api/settings/user-notifications")
def api_update_user_notifications(body: UserNotificationUpdate, actor: Dict[str, Any] = Depends(get_current_user)) -> JSONResponse:
    from bsm.settings import get_access_user, upsert_access_user

    username = (body.username or "").strip()
    if not username:
        return JSONResponse({"error": "username is required"}, status_code=422)
    if not _can_access_user(actor, username):
        return _forbidden()

    user = get_access_user(username)
    if not user:
        return JSONResponse({"error": "user not found"}, status_code=404)

    notify_enabled = bool(user.get("notify_enabled", True) if body.notify_enabled is None else body.notify_enabled)
    keywords = user.get("keywords") if body.keywords is None else body.keywords
    telegram_ids = user.get("telegram_ids") if body.telegram_ids is None else body.telegram_ids

    upsert_access_user(
        username=username,
        display_name=str(user.get("display_name") or ""),
        password_hash=str(user.get("password_hash") or ""),
        telegram_ids=telegram_ids,
        keywords=keywords,
        roles=user.get("roles") or [],
        status=str(user.get("status") or "active"),
        notify_enabled=notify_enabled,
    )

    return JSONResponse({
        "ok": True,
        "user": {
            "username": username,
            "notify_enabled": notify_enabled,
            "keywords": keywords or [],
            "telegram_ids": telegram_ids or [],
        },
    })


@router.post("/api/settings/user-notifications/test")
async def api_test_user_notifications(body: UserNotificationUpdate, actor: Dict[str, Any] = Depends(get_current_user)) -> JSONResponse:
    from bsm.settings import get_access_user, load_runtime_config
    from bsm.telegrambot import TelegramBot

    username = (body.username or "").strip()
    if not username:
        return JSONResponse({"error": "username is required"}, status_code=422)
    if not _can_access_user(actor, username):
        return _forbidden()

    user = get_access_user(username)
    if not user:
        return JSONResponse({"error": "user not found"}, status_code=404)

    keywords = [str(item).strip() for item in (body.keywords if body.keywords is not None else (user.get("keywords") or [])) if str(item).strip()]
    telegram_ids = [str(item).strip() for item in (body.telegram_ids if body.telegram_ids is not None else (user.get("telegram_ids") or [])) if str(item).strip()]

    if not telegram_ids:
        return JSONResponse({"error": "telegram_ids are required"}, status_code=422)

    cfg = load_runtime_config()
    tg = (cfg.get("telegram") or {})
    if not tg.get("bot_token"):
        return JSONResponse({"error": "telegram bot token is not configured"}, status_code=422)

    timezone_name = str(cfg.get("timezone") or "Asia/Shanghai")
    try:
        now_text = datetime.now(ZoneInfo(timezone_name)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        timezone_name = "Asia/Shanghai"
        now_text = datetime.now(ZoneInfo(timezone_name)).strftime("%Y-%m-%d %H:%M:%S")

    bot = TelegramBot(str(tg.get("bot_token")))
    text = f"通知测试\n当前时间: {now_text}\n时区: {timezone_name}"
    app_base_url = str(cfg.get("app_base_url") or "").strip().rstrip("/")
    if app_base_url:
        text += f"\n应用首页: {app_base_url}/notifications"
    if keywords:
        text += "\n当前关键词:\n" + "\n".join(f"- {keyword}" for keyword in keywords)
    sent = 0
    failed: List[str] = []
    for chat_id in telegram_ids:
        ok = bot.send_text_to(chat_id, text)
        if ok:
            sent += 1
        else:
            failed.append(chat_id)

    if sent == 0:
        return JSONResponse({"error": "failed to send test notification", "failed_chat_ids": failed}, status_code=502)

    return JSONResponse({"ok": True, "sent": sent, "failed_chat_ids": failed})


@router.get("/api/settings/db-ping")
def api_ping_db(_: Dict[str, Any] = Depends(get_current_admin)) -> JSONResponse:
    import time
    from bsm.db import ping_database
    try:
        start = time.perf_counter()
        ping_database()
        latency = (time.perf_counter() - start) * 1000
        return JSONResponse({"latency_ms": round(latency, 2), "error": None})
    except Exception as e:
        return JSONResponse({"latency_ms": None, "error": str(e)})


@router.get("/api/settings/db-size")
def api_db_size_diagnostics(
    days: int = 7,
    top_n: int = 20,
    _: Dict[str, Any] = Depends(get_current_admin),
) -> JSONResponse:
    from bsm.db import get_database_size_report

    if days < 1 or days > 3650:
        return JSONResponse({"error": "days must be between 1 and 3650"}, status_code=422)
    if top_n < 1 or top_n > 200:
        return JSONResponse({"error": "top_n must be between 1 and 200"}, status_code=422)
    try:
        report = get_database_size_report(days=days, top_n=top_n)
        return JSONResponse(report)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.put("/api/settings")
async def api_update_settings(body: SettingsUpdate, _: Dict[str, Any] = Depends(get_current_admin)) -> JSONResponse:
    from bsm.settings import reset_public_account_settings_cache, save_yaml_config_value

    updated: Dict[str, Any] = {}
    restarted_cron = False
    
    def _save_setting(key: str, value: Any) -> None:
        try:
            save_yaml_config_value(key, value)
        except Exception as exc:
            raise RuntimeError(f"failed to persist '{key}': {exc}") from exc
    try:
        if body.scan_mode is not None:
            if body.scan_mode not in ("latest", "continue", "continue_until_repeat"):
                return JSONResponse(
                    {"error": "scan_mode must be 'latest', 'continue', or 'continue_until_repeat'"},
                    status_code=422,
                )
            _save_setting("scan_mode", body.scan_mode)
            updated["scan_mode"] = body.scan_mode

        if body.interval is not None:
            if body.interval < 5:
                return JSONResponse({"error": "interval must be >= 5 seconds"}, status_code=422)
            _save_setting("interval", body.interval)
            updated["interval"] = body.interval

        if body.category is not None:
            _save_setting("category", body.category)
            updated["category"] = body.category

        if body.timezone is not None:
            _save_setting("timezone", body.timezone)
            updated["timezone"] = body.timezone

        if body.app_base_url is not None:
            app_base_url = str(body.app_base_url).strip().rstrip("/")
            _save_setting("app_base_url", app_base_url)
            updated["app_base_url"] = app_base_url

        if body.cloudflare_validation_enabled is not None:
            cloudflare_validation_enabled = bool(body.cloudflare_validation_enabled)
            _save_setting("cloudflare_validation_enabled", cloudflare_validation_enabled)
            updated["cloudflare_validation_enabled"] = cloudflare_validation_enabled

        if body.cloudflare_turnstile_site_key is not None:
            cloudflare_turnstile_site_key = str(body.cloudflare_turnstile_site_key).strip()
            _save_setting("cloudflare_turnstile_site_key", cloudflare_turnstile_site_key)
            updated["cloudflare_turnstile_site_key"] = cloudflare_turnstile_site_key

        if body.cloudflare_turnstile_secret_key is not None:
            cloudflare_turnstile_secret_key = str(body.cloudflare_turnstile_secret_key).strip()
            _save_setting("cloudflare_turnstile_secret_key", cloudflare_turnstile_secret_key)
            updated["cloudflare_turnstile_secret_key_configured"] = bool(cloudflare_turnstile_secret_key)

        if body.bili_session_pick_mode is not None:
            if body.bili_session_pick_mode not in ("round_robin", "random"):
                return JSONResponse({"error": "bili_session_pick_mode must be 'round_robin' or 'random'"}, status_code=422)
            _save_setting("bili_session_pick_mode", body.bili_session_pick_mode)
            updated["bili_session_pick_mode"] = body.bili_session_pick_mode

        if body.bili_session_cooldown_seconds is not None:
            if body.bili_session_cooldown_seconds < 0:
                return JSONResponse({"error": "bili_session_cooldown_seconds must be >= 0"}, status_code=422)
            _save_setting("bili_session_cooldown_seconds", body.bili_session_cooldown_seconds)
            updated["bili_session_cooldown_seconds"] = body.bili_session_cooldown_seconds

        if body.admin_scan_summary_interval_seconds is not None:
            if body.admin_scan_summary_interval_seconds <= 0:
                return JSONResponse({"error": "admin_scan_summary_interval_seconds must be > 0"}, status_code=422)
            _save_setting("admin_scan_summary_interval_seconds", body.admin_scan_summary_interval_seconds)
            updated["admin_scan_summary_interval_seconds"] = body.admin_scan_summary_interval_seconds

        if body.admin_telegram_ids is not None:
            admin_telegram_ids: List[str] = []
            seen_admin_ids = set()
            for item in body.admin_telegram_ids:
                text = str(item).strip()
                if not text or text in seen_admin_ids:
                    continue
                seen_admin_ids.add(text)
                admin_telegram_ids.append(text)
            _save_setting("admin_telegram_ids", admin_telegram_ids)
            updated["admin_telegram_ids"] = admin_telegram_ids

        if body.price_filters is not None:
            price_filters = _normalize_filter_selection(body.price_filters, _ALL_PRICE_FILTERS)
            _save_setting("price_filters", price_filters)
            updated["price_filters"] = price_filters

        if body.discount_filters is not None:
            discount_filters = _normalize_filter_selection(body.discount_filters, _ALL_DISCOUNT_FILTERS)
            _save_setting("discount_filters", discount_filters)
            updated["discount_filters"] = discount_filters

        if updated:
            reset_public_account_settings_cache()
        if body.interval is not None:
            from backend.main import restart_cron_task

            await restart_cron_task()
            restarted_cron = True
    except Exception as exc:
        return JSONResponse({"error": f"failed to save settings: {exc}"}, status_code=500)

    return JSONResponse({"ok": True, "updated": updated, "restarted_cron": restarted_cron})
