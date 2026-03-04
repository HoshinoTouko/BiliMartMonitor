from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

_SRC_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _SRC_ROOT not in sys.path:
    sys.path.insert(0, _SRC_ROOT)

from backend.auth import authenticate_access_user, get_current_user, get_current_admin  # noqa: E402
from backend.cron_state import cron_state  # noqa: E402

router = APIRouter()


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class AccountUpsertRequest(BaseModel):
    username: str
    display_name: Optional[str] = None
    password: Optional[str] = None
    roles: Optional[List[str]] = None
    status: Optional[str] = None
    notify_enabled: Optional[bool] = None
    keywords: Optional[List[str]] = None
    telegram_ids: Optional[List[str]] = None


def _forbidden(message: str = "forbidden") -> JSONResponse:
    return JSONResponse({"detail": message}, status_code=403)


def _unauthorized() -> JSONResponse:
    return JSONResponse({"detail": "authentication required"}, status_code=401)


def _normalize_roles(raw_roles: Optional[List[str]]) -> List[str]:
    result: List[str] = []
    seen = set()
    for raw in raw_roles or []:
        role = str(raw or "").strip().lower()
        if not role or role in seen:
            continue
        seen.add(role)
        result.append(role)
    return result


def _account_payload(user: Dict[str, Any]) -> Dict[str, Any]:
    roles = user.get("roles") or []
    role = "admin" if "admin" in roles else "user"
    return {
        "username": str(user.get("username") or ""),
        "display_name": str(user.get("display_name") or ""),
        "role": role,
        "roles": roles,
        "status": str(user.get("status") or "active"),
        "notify_enabled": bool(user.get("notify_enabled", True)),
        "keywords": user.get("keywords") or [],
        "telegram_ids": user.get("telegram_ids") or [],
    }


@router.get("/api/account/me")
async def api_get_current_account(user: Dict[str, Any] = Depends(get_current_user)) -> JSONResponse:
    return JSONResponse({"ok": True, "account": _account_payload(user)})


@router.get("/api/account/dashboard")
async def api_get_account_dashboard(_: Dict[str, Any] = Depends(get_current_user)) -> JSONResponse:
    from bsm.db import count_items, list_bili_sessions
    from bsm.settings import list_access_users

    cron = cron_state.to_dict()
    return JSONResponse(
        {
            "ok": True,
            "today_refresh_count": int(cron.get("today_scans") or 0),
            "today_new_item_count": int(cron.get("today_inserted") or 0),
            "user_count": len(list_access_users(status="active")),
            "active_session_count": len(list_bili_sessions(status="active")),
            "item_count": count_items(),
            "last_scan_at": cron.get("last_scan_at"),
            "is_running": bool(cron.get("is_running")),
        }
    )


@router.get("/api/account/db-ping")
async def api_ping_account_db(_: Dict[str, Any] = Depends(get_current_user)) -> JSONResponse:
    import time
    from bsm.db import ping_database

    try:
        start = time.perf_counter()
        ping_database()
        latency = (time.perf_counter() - start) * 1000
        return JSONResponse({"latency_ms": round(latency, 2), "error": None})
    except Exception as e:
        return JSONResponse({"latency_ms": None, "error": str(e)})


@router.put("/api/account/me/password")
async def api_change_my_password(body: PasswordChangeRequest, user: Dict[str, Any] = Depends(get_current_user)) -> JSONResponse:
    from bsm.settings import upsert_access_user

    if not authenticate_access_user(str(user.get("username") or ""), str(body.current_password or "")):
        return JSONResponse({"detail": "current password is incorrect"}, status_code=422)

    new_password = str(body.new_password or "")
    if len(new_password) < 4:
        return JSONResponse({"error": "new password must be at least 4 characters"}, status_code=422)

    upsert_access_user(
        username=str(user["username"]),
        display_name=str(user.get("display_name") or ""),
        password_hash=new_password,
        telegram_ids=user.get("telegram_ids") or [],
        keywords=user.get("keywords") or [],
        roles=user.get("roles") or [],
        status=str(user.get("status") or "active"),
        notify_enabled=bool(user.get("notify_enabled", True)),
    )
    return JSONResponse({"ok": True})


@router.get("/api/account/users")
async def api_list_accounts(_: Dict[str, Any] = Depends(get_current_admin)) -> JSONResponse:
    from bsm.settings import list_access_users

    users = [_account_payload(item) for item in list_access_users(status=None)]
    return JSONResponse({"ok": True, "users": users})


@router.post("/api/account/users")
async def api_upsert_account(body: AccountUpsertRequest, _: Dict[str, Any] = Depends(get_current_admin)) -> JSONResponse:
    from bsm.settings import get_access_user, upsert_access_user

    username = str(body.username or "").strip()
    if not username:
        return JSONResponse({"error": "username is required"}, status_code=422)

    existing = get_access_user(username)
    if existing is not None:
        return JSONResponse({"error": "username already exists"}, status_code=409)

    # For new user, we normally require a password. 
    # But if the admin explicitly sends "", we allow it (though it's effectively "no password").
    # If it's missing entirely (None), we error.
    if body.password is None:
        return JSONResponse({"error": "password is required for new user"}, status_code=422)
    
    roles = _normalize_roles(body.roles or ["user"])
    if not roles:
        roles = ["user"]
    status = str(body.status or "active").strip() or "active"
    notify_enabled = True if body.notify_enabled is None else bool(body.notify_enabled)
    upsert_access_user(
        username=username,
        display_name=str(body.display_name or username),
        password_hash=str(body.password or ""),
        telegram_ids=body.telegram_ids or [],
        keywords=body.keywords or [],
        roles=roles,
        status=status,
        notify_enabled=notify_enabled,
    )

    saved = get_access_user(username)
    return JSONResponse({"ok": True, "user": _account_payload(saved or {"username": username})})


@router.put("/api/account/users/{old_username}")
async def api_update_account(old_username: str, body: AccountUpsertRequest, _: Dict[str, Any] = Depends(get_current_admin)) -> JSONResponse:
    from bsm.settings import get_access_user, upsert_access_user, delete_access_user

    old_username = str(old_username or "").strip()
    new_username = str(body.username or "").strip()

    if not new_username:
        return JSONResponse({"error": "username is required"}, status_code=422)

    existing = get_access_user(old_username)
    if existing is None:
        return JSONResponse({"error": "user not found"}, status_code=404)

    # If username is changing, check for conflict
    if new_username != old_username:
        if get_access_user(new_username):
            return JSONResponse({"error": "new username already exists"}, status_code=409)

    # Password logic: preserve if empty string/None, unless explicitly changing
    # Actually, for modification, if someone sends "", it usually means "don't change" 
    # BUT we allowed "" for creation. 
    # Let's stick to the user's original rule: blank password means no change during Edit.
    password_hash = (
        str(body.password)
        if body.password is not None and str(body.password) != ""
        else str(existing.get("password_hash") or "")
    )
    
    roles = _normalize_roles(body.roles if body.roles is not None else (existing.get("roles") or []))
    if not roles:
        roles = ["user"]
    
    status = str(body.status or existing.get("status") or "active").strip() or "active"
    notify_enabled = bool(existing.get("notify_enabled", True) if body.notify_enabled is None else body.notify_enabled)

    # If changing username, we must delete the old record and create a new one
    # (since the DB key is often the username in the settings layer)
    if new_username != old_username:
        delete_access_user(old_username)

    upsert_access_user(
        username=new_username,
        display_name=str(body.display_name if body.display_name is not None else (existing.get("display_name") or new_username)),
        password_hash=password_hash,
        telegram_ids=body.telegram_ids if body.telegram_ids is not None else (existing.get("telegram_ids") or []),
        keywords=body.keywords if body.keywords is not None else (existing.get("keywords") or []),
        roles=roles,
        status=status,
        notify_enabled=notify_enabled,
    )

    saved = get_access_user(new_username)
    return JSONResponse({"ok": True, "user": _account_payload(saved or {"username": new_username})})


@router.delete("/api/account/users/{username}")
async def api_delete_account(username: str, actor: Dict[str, Any] = Depends(get_current_admin)) -> JSONResponse:
    from bsm.settings import delete_access_user, get_access_user

    target = str(username or "").strip()
    if not target:
        return JSONResponse({"error": "username is required"}, status_code=422)
    if target == str(actor.get("username") or ""):
        return JSONResponse({"error": "cannot delete current account"}, status_code=422)
    if not get_access_user(target):
        return JSONResponse({"error": "user not found"}, status_code=404)

    delete_access_user(target)
    return JSONResponse({"ok": True})

# --- Telegram Binding ---

@router.post("/api/account/telegram/bind-code")
async def api_generate_bind_code(
    user: Dict[str, Any] = Depends(get_current_user)
):
    import random
    import string
    import time
    from bsm.telegrambot import PENDING_BINDS, PENDING_BIND_TTL_SECONDS, prune_expired_binds
    username = str(user.get("username") or "")
    prune_expired_binds()
    code = "".join(random.choices(string.digits, k=6))
    PENDING_BINDS[username] = (code, time.time() + PENDING_BIND_TTL_SECONDS)
    return {"ok": True, "code": code}

@router.post("/api/account/telegram/refresh")
async def api_trigger_telegram_refresh(
    _: Dict[str, Any] = Depends(get_current_user)
):
    from bsm.telegrambot import trigger_bot_update
    trigger_bot_update()
    return {"ok": True}
