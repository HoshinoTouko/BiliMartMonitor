"""
BSM FastAPI backend — auth helpers.

Bridges straight to src/bsm/db without any Reflex session handling.
Primary auth uses a signed HttpOnly session cookie; Basic auth is kept as a
backward-compatible fallback for scripts and tests.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import sys
import threading
import time
from typing import Optional, Tuple, Dict, Any

from fastapi import Request, Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

# ---------------------------------------------------------------------------
# Ensure src/ is on the path so we can import bsm.*
# ---------------------------------------------------------------------------
_SRC_ROOT = os.path.dirname(os.path.dirname(__file__))
_PROJECT_ROOT = os.path.dirname(_SRC_ROOT)
if _SRC_ROOT not in sys.path:
    sys.path.insert(0, _SRC_ROOT)

from bsm import db  # noqa: E402
from bsm import settings
from bsm.passwords import is_password_hash, verify_password

security = HTTPBasic(auto_error=False)

DEMO_ADMIN_USERNAME = "admin"
SESSION_COOKIE_NAME = "bsm_session"
SESSION_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
_DEFAULT_SESSION_SECRET = "bsm-dev-session-secret-change-me"

_DEFAULT_ADMIN = {
    "username": DEMO_ADMIN_USERNAME,
    "display_name": "Admin",
    "password_hash": "admin",
    "roles": ["admin"],
    "status": "active",
}
_DEFAULT_ACCESS_USERS_ENSURED = False
_FAIL2BAN_LOCK = threading.Lock()
_FAIL2BAN_WINDOW_SECONDS = 300.0
_FAIL2BAN_BAN_SECONDS = 900.0
_FAIL2BAN_MAX_FAILURES = 5
_FAIL2BAN_STATE: Dict[str, Dict[str, Any]] = {}


def ensure_default_access_users() -> None:
    """Seed the admin user if the table is empty."""
    global _DEFAULT_ACCESS_USERS_ENSURED

    if _DEFAULT_ACCESS_USERS_ENSURED:
        return

    users = settings.list_access_users()
    if users:
        _DEFAULT_ACCESS_USERS_ENSURED = True
        return
    settings.upsert_access_user(
        username=_DEFAULT_ADMIN["username"],
        display_name=_DEFAULT_ADMIN["display_name"],
        password_hash=_DEFAULT_ADMIN["password_hash"],
        roles=_DEFAULT_ADMIN["roles"],
        status=_DEFAULT_ADMIN["status"],
    )
    _DEFAULT_ACCESS_USERS_ENSURED = True


def authenticate_access_user(username: str, password: str) -> Optional[Dict[str, Any]]:
    ensure_default_access_users()
    username = (username or "").strip()
    user = settings.get_access_user(username)
    if not user:
        return None
    if str(user.get("status") or "") != "active":
        return None
    stored_password = str(user.get("password_hash") or "")
    plain_password = str(password or "")
    password_ok = False
    needs_upgrade = False
    if is_password_hash(stored_password):
        password_ok = verify_password(plain_password, stored_password)
    else:
        password_ok = stored_password == plain_password
        needs_upgrade = password_ok and bool(stored_password)
    if not password_ok:
        return None
    if needs_upgrade:
        settings.upsert_access_user(
            username=str(user.get("username") or ""),
            display_name=str(user.get("display_name") or ""),
            password_hash=plain_password,
            telegram_ids=user.get("telegram_ids") or [],
            keywords=user.get("keywords") or [],
            roles=user.get("roles") or [],
            status=str(user.get("status") or "active"),
            notify_enabled=bool(user.get("notify_enabled", True)),
        )
        refreshed = settings.get_access_user(username)
        if refreshed:
            user = refreshed
    roles = user.get("roles") or []
    role = "admin" if "admin" in roles else "user"
    return {
        "username": user["username"],
        "role": role,
        "display_name": user.get("display_name") or user["username"],
        "roles": roles,
        "status": user.get("status") or "active",
        "notify_enabled": bool(user.get("notify_enabled", True)),
        "keywords": user.get("keywords") or [],
        "telegram_ids": user.get("telegram_ids") or [],
    }


def _session_secret() -> bytes:
    raw = str(os.environ.get("BSM_SESSION_SECRET") or "").strip()
    return (raw or _DEFAULT_SESSION_SECRET).encode("utf-8")


def _session_signature(username: str, expires_at: int) -> str:
    payload = f"{username}:{expires_at}".encode("utf-8")
    return hmac.new(_session_secret(), payload, hashlib.sha256).hexdigest()


def create_session_token(username: str) -> str:
    expires_at = int(time.time()) + SESSION_MAX_AGE_SECONDS
    signature = _session_signature(username, expires_at)
    raw = f"{username}:{expires_at}:{signature}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_session_token(token: str) -> Optional[Tuple[str, int, str]]:
    text = str(token or "").strip()
    if not text:
        return None
    padding = "=" * (-len(text) % 4)
    try:
        raw = base64.urlsafe_b64decode((text + padding).encode("ascii")).decode("utf-8")
    except Exception:
        return None
    username, expires_text, signature = raw.split(":", 2) if raw.count(":") >= 2 else ("", "", "")
    if not username or not expires_text or not signature:
        return None
    try:
        expires_at = int(expires_text)
    except Exception:
        return None
    return username, expires_at, signature


def authenticate_session_token(token: str) -> Optional[Dict[str, Any]]:
    parsed = _decode_session_token(token)
    if not parsed:
        return None
    username, expires_at, signature = parsed
    if expires_at < int(time.time()):
        return None
    expected = _session_signature(username, expires_at)
    if not hmac.compare_digest(signature, expected):
        return None
    user = settings.get_access_user(username)
    if not user or str(user.get("status") or "") != "active":
        return None
    roles = user.get("roles") or []
    role = "admin" if "admin" in roles else "user"
    return {
        "username": user["username"],
        "role": role,
        "display_name": user.get("display_name") or user["username"],
        "roles": roles,
        "status": user.get("status") or "active",
        "notify_enabled": bool(user.get("notify_enabled", True)),
        "keywords": user.get("keywords") or [],
        "telegram_ids": user.get("telegram_ids") or [],
    }


def _client_ip(value: Optional[str]) -> str:
    text = str(value or "").strip()
    return text or "unknown"


def get_client_ip(connection: Any) -> str:
    headers = getattr(connection, "headers", None)
    if headers:
        for key in ("cf-connecting-ip", "x-forwarded-for", "x-real-ip"):
            raw_value = str(headers.get(key) or "").strip()
            if not raw_value:
                continue
            if key == "x-forwarded-for":
                raw_value = raw_value.split(",")[0].strip()
            if raw_value:
                return raw_value
    client = getattr(connection, "client", None)
    host = getattr(client, "host", "") if client else ""
    return _client_ip(host)


def _is_banned(client_ip: str) -> float:
    now = time.monotonic()
    with _FAIL2BAN_LOCK:
        state = _FAIL2BAN_STATE.get(client_ip)
        if not state:
            return 0.0
        banned_until = float(state.get("banned_until", 0.0) or 0.0)
        if banned_until <= now:
            if not state.get("failures"):
                _FAIL2BAN_STATE.pop(client_ip, None)
            else:
                state["banned_until"] = 0.0
            return 0.0
        return max(0.0, banned_until - now)


def _clear_failures(client_ip: str) -> None:
    with _FAIL2BAN_LOCK:
        _FAIL2BAN_STATE.pop(client_ip, None)


def _record_failure(client_ip: str, username: str) -> Tuple[bool, float]:
    now = time.monotonic()
    with _FAIL2BAN_LOCK:
        state = _FAIL2BAN_STATE.setdefault(client_ip, {"failures": [], "banned_until": 0.0, "last_alert": 0.0})
        state["failures"] = [ts for ts in state.get("failures", []) if now - float(ts) <= _FAIL2BAN_WINDOW_SECONDS]
        state["failures"].append(now)
        if len(state["failures"]) < _FAIL2BAN_MAX_FAILURES:
            return False, 0.0
        banned_until = now + _FAIL2BAN_BAN_SECONDS
        state["banned_until"] = banned_until
        state["failures"] = []
        return True, _FAIL2BAN_BAN_SECONDS


def _should_send_ban_alert(client_ip: str) -> bool:
    now = time.monotonic()
    with _FAIL2BAN_LOCK:
        state = _FAIL2BAN_STATE.setdefault(client_ip, {"failures": [], "banned_until": 0.0, "last_alert": 0.0})
        last_alert = float(state.get("last_alert", 0.0) or 0.0)
        if now - last_alert < 60.0:
            return False
        state["last_alert"] = now
        return True


def _send_fail2ban_alert(message: str) -> None:
    try:
        from bsm.notify import send_admin_telegram_alert
        send_admin_telegram_alert(message)
    except Exception:
        pass


def reject_if_banned(client_ip: Optional[str]) -> Optional[HTTPException]:
    normalized_ip = _client_ip(client_ip)
    remaining = _is_banned(normalized_ip)
    if remaining <= 0:
        return None
    if _should_send_ban_alert(normalized_ip):
        _send_fail2ban_alert(
            f"系统告警\n类型: Fail2Ban 命中\n来源 IP: {normalized_ip}\n状态: 封禁中\n剩余: {int(remaining)} 秒"
        )
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=f"Too many failed attempts. Try again in {int(remaining)} seconds.",
    )


def record_failed_auth_attempt(client_ip: Optional[str], username: str) -> Optional[HTTPException]:
    normalized_ip = _client_ip(client_ip)
    banned, ban_seconds = _record_failure(normalized_ip, username)
    if not banned:
        return None
    if _should_send_ban_alert(normalized_ip):
        _send_fail2ban_alert(
            f"系统告警\n类型: 密码爆破拦截\n来源 IP: {normalized_ip}\n用户名: {username or '-'}\n动作: 已封禁 {int(ban_seconds)} 秒"
        )
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=f"Too many failed attempts. Try again in {int(ban_seconds)} seconds.",
    )


def clear_failed_auth_attempts(client_ip: Optional[str]) -> None:
    _clear_failures(_client_ip(client_ip))


def cloudflare_validation_settings() -> Dict[str, Any]:
    cfg = settings.load_runtime_config()
    return {
        "enabled": bool(cfg.get("cloudflare_validation_enabled", False)),
        "site_key": str(cfg.get("cloudflare_turnstile_site_key") or "").strip(),
        "secret_key": str(cfg.get("cloudflare_turnstile_secret_key") or "").strip(),
    }


def verify_cloudflare_token(token: str, client_ip: str) -> Tuple[bool, str]:
    import requests

    cf = cloudflare_validation_settings()
    if not cf["enabled"]:
        return True, ""
    if not token:
        return False, "Cloudflare verification is required"
    if not cf["secret_key"]:
        return False, "Cloudflare Turnstile secret is not configured"

    try:
        resp = requests.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={
                "secret": cf["secret_key"],
                "response": token,
                "remoteip": client_ip,
            },
            timeout=8,
        )
        payload = resp.json()
    except Exception:
        return False, "Cloudflare verification failed"

    if bool(payload.get("success")):
        return True, ""
    return False, "Cloudflare verification failed"


def authenticate_credentials(username: str, password: str) -> Optional[Tuple[str, str]]:
    user = authenticate_access_user(username, password)
    if not user:
        return None
    return str(user["username"]), str(user["role"])


def get_current_user(request: Request, credentials: Optional[HTTPBasicCredentials] = Depends(security)) -> Dict[str, Any]:
    """Dependency to get the current authenticated user."""
    session_user = authenticate_session_token(str(request.cookies.get(SESSION_COOKIE_NAME) or ""))
    if session_user:
        return session_user
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    client_ip = get_client_ip(request)
    blocked = reject_if_banned(client_ip)
    if blocked:
        raise blocked
    user = authenticate_access_user(credentials.username, credentials.password)
    if not user:
        blocked = record_failed_auth_attempt(client_ip, credentials.username)
        if blocked:
            raise blocked
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    clear_failed_auth_attempts(client_ip)
    return user


def get_current_admin(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Dependency to ensure the current user is an admin."""
    if "admin" not in (user.get("roles") or []):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return user


def get_authenticated_user(request: Request) -> Optional[Dict[str, Any]]:
    """Legacy helper for manual auth checks from cookies or Request headers."""
    session_user = authenticate_session_token(str(request.cookies.get(SESSION_COOKIE_NAME) or ""))
    if session_user:
        return session_user

    header = str(request.headers.get("authorization") or "").strip()
    if not header.lower().startswith("basic "):
        return None

    token = header[6:].strip()
    if not token:
        return None

    try:
        raw = base64.b64decode(token).decode("utf-8")
    except Exception:
        return None

    username, _, password = raw.partition(":")
    if not username:
        return None
    return authenticate_access_user(username, password)
