import threading
import time
from typing import Any, Dict, List, Optional, Iterable

from .env import ensure_initial_project_config, load_dotenv


_ACCESS_USER_MIGRATION_CHECKED = False
_PUBLIC_ACCOUNT_SETTINGS_CACHE_TTL_SECONDS = 300.0
_PUBLIC_ACCOUNT_SETTINGS_CACHE_LOCK = threading.Lock()
_PUBLIC_ACCOUNT_SETTINGS_CACHE: Dict[str, Any] = {
    "value": None,
    "expires_at": 0.0,
}

_ACCESS_USER_CACHE_TTL_SECONDS = 600.0
_ACCESS_USER_CACHE_LOCK = threading.Lock()
_ACCESS_USER_CACHE: Dict[str, Dict[str, Any]] = {}


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        return default
    return parsed if parsed > 0 else default


def _non_negative_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        return default
    return parsed if parsed >= 0 else default


def _positive_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except Exception:
        return default
    return parsed if parsed > 0 else default


def _session_pick_mode(value: Any, default: str = "round_robin") -> str:
    mode = str(value or default).strip().lower()
    if mode not in {"round_robin", "random"}:
        return default
    return mode


def _api_request_mode(value: Any, default: str = "async") -> str:
    mode = str(value or default).strip().lower()
    if mode not in {"sync", "async"}:
        return default
    return mode


def _yaml_config_path(*, for_write: bool = False) -> str:
    from .env import data_dir, project_root, resolve_project_path
    import os

    override = resolve_project_path(os.environ.get("BSM_CONFIG_PATH", "").strip())
    if override:
        return override

    root_path = os.path.join(project_root(), "config.yaml")
    if for_write or os.path.exists(root_path):
        return root_path

    return os.path.join(data_dir(), "config.yaml")


def load_yaml_config() -> Dict[str, Any]:
    import os
    try:
        import yaml
    except ModuleNotFoundError:
        return {}

    ensure_initial_project_config()
    path = _yaml_config_path()
    if not os.path.exists(path):
        return {}
        
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def save_yaml_config_value(key: str, value: Any) -> None:
    import os
    try:
        import yaml
    except ModuleNotFoundError:
        raise RuntimeError("PyYAML is required to save config")

    load_dotenv()
    path = _yaml_config_path(for_write=True)
    data = load_yaml_config()
    if value is None:
        data.pop(key, None)
    else:
        data[key] = value

    try:
        parent_dir = os.path.dirname(path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    except Exception as exc:
        raise RuntimeError(f"failed to write config file '{path}': {exc}") from exc


def _normalize_string_list(value: Any) -> List[str]:
    if isinstance(value, list):
        raw_values = value
    elif isinstance(value, tuple):
        raw_values = list(value)
    elif isinstance(value, str):
        raw_values = [value]
    elif value is None:
        raw_values = []
    else:
        raw_values = [value]
    normalized: List[str] = []
    seen = set()
    for item in raw_values:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def _legacy_yaml_access_users() -> List[Dict[str, Any]]:
    yaml_config = load_yaml_config()
    users = yaml_config.get("users", [])
    if not isinstance(users, list):
        return []
    result: List[Dict[str, Any]] = []
    for raw in users:
        if not isinstance(raw, dict):
            continue
        telegram_ids = _normalize_string_list(raw.get("telegram_ids"))
        if not telegram_ids:
            telegram_ids = _normalize_string_list(raw.get("telegram_id"))
        result.append({
            "username": str(raw.get("username") or "").strip(),
            "display_name": str(raw.get("display_name") or ""),
            "password_hash": str(raw.get("password_hash") or ""),
            "telegram_ids": telegram_ids,
            "keywords": _normalize_string_list(raw.get("keywords")),
            "roles": _normalize_string_list(raw.get("roles")),
            "status": str(raw.get("status") or "active"),
            "notify_enabled": bool(raw.get("notify_enabled", True)),
        })
    return [user for user in result if user["username"]]


def _migrate_yaml_users_to_db_if_needed() -> None:
    global _ACCESS_USER_MIGRATION_CHECKED

    if _ACCESS_USER_MIGRATION_CHECKED:
        return

    from . import db

    current_users = db.list_access_users(status=None)
    if current_users:
        _ACCESS_USER_MIGRATION_CHECKED = True
        return
    legacy_users = _legacy_yaml_access_users()
    if not legacy_users:
        _ACCESS_USER_MIGRATION_CHECKED = True
        return
    for user in legacy_users:
        db.upsert_access_user(
            username=user["username"],
            display_name=user["display_name"],
            password_hash=user["password_hash"],
            telegram_ids=user["telegram_ids"],
            keywords=user["keywords"],
            roles=user["roles"],
            status=user["status"],
            notify_enabled=user["notify_enabled"],
        )
    _ACCESS_USER_MIGRATION_CHECKED = True

def load_runtime_config() -> Dict[str, Any]:
    load_dotenv()
    yaml_config = load_yaml_config()
    
    cfg = {
        "scan_mode": yaml_config.get("scan_mode", "latest"),
        "interval": yaml_config.get("interval", 20),
        "category": yaml_config.get("category", ""),
        "sort_type": yaml_config.get("sort_type", "TIME_DESC"),
        "timezone": yaml_config.get("timezone", "Asia/Shanghai"),
        "app_base_url": yaml_config.get("app_base_url", ""),
        "cloudflare_validation_enabled": bool(yaml_config.get("cloudflare_validation_enabled", False)),
        "cloudflare_turnstile_site_key": yaml_config.get("cloudflare_turnstile_site_key", ""),
        "cloudflare_turnstile_secret_key": yaml_config.get("cloudflare_turnstile_secret_key", ""),
        "bili_session_pick_mode": _session_pick_mode(
            yaml_config.get("bili_session_pick_mode", "round_robin"),
        ),
        "bili_session_cooldown_seconds": _non_negative_int(
            yaml_config.get("bili_session_cooldown_seconds", 60),
            60,
        ),
        "admin_scan_summary_interval_seconds": _positive_int(
            yaml_config.get("admin_scan_summary_interval_seconds", 600),
            600,
        ),
        "api_request_mode": _api_request_mode(
            yaml_config.get("api_request_mode", "async"),
            "async",
        ),
        "scan_timeout_seconds": _positive_float(
            yaml_config.get("scan_timeout_seconds", 15),
            15.0,
        ),
    }
    cfg["admin_telegram_ids"] = _normalize_string_list(yaml_config.get("admin_telegram_ids"))
    price_filters = yaml_config.get("price_filters")
    discount_filters = yaml_config.get("discount_filters")
    cfg["price_filters"] = _normalize_string_list(price_filters) if price_filters is not None else None
    cfg["discount_filters"] = _normalize_string_list(discount_filters) if discount_filters is not None else None
    yaml_notify = yaml_config.get("notify", {})
    yaml_email = yaml_notify.get("email", {})
    yaml_sms = yaml_notify.get("sms", {})

    cfg["notify"] = {
        "email": {
            "enabled": bool(yaml_email.get("enabled", False)),
            "smtp_server": yaml_email.get("smtp_server", ""),
            "smtp_port": yaml_email.get("smtp_port", 0),
            "username": yaml_email.get("username", ""),
            "password": yaml_email.get("password", ""),
            "to": _normalize_string_list(yaml_email.get("to")),
        },
        "sms": {
            "enabled": bool(yaml_sms.get("enabled", False)),
            "provider": yaml_sms.get("provider", ""),
            "api_key": yaml_sms.get("api_key", ""),
            "to": _normalize_string_list(yaml_sms.get("to")),
        },
    }

    ytg = yaml_config.get("telegram", {})
    cfg["telegram"] = {
        "enabled": bool(ytg.get("enabled", False)),
        "notify": bool(ytg.get("notify", True)),
        "bot_id": ytg.get("bot_id", ""),
        "bot_token": ytg.get("bot_token", ""),
        "poll_interval": ytg.get("poll_interval", 10),
    }
    return cfg


def list_runtime_settings() -> Dict[str, Any]:
    cfg = load_runtime_config()
    return {
        "scan_mode": cfg.get("scan_mode"),
        "interval": cfg.get("interval"),
        "category": cfg.get("category"),
        "timezone": cfg.get("timezone"),
        "app_base_url": cfg.get("app_base_url"),
        "cloudflare_validation_enabled": bool(cfg.get("cloudflare_validation_enabled", False)),
        "cloudflare_turnstile_site_key": cfg.get("cloudflare_turnstile_site_key", ""),
        "cloudflare_turnstile_secret_key": cfg.get("cloudflare_turnstile_secret_key", ""),
        "bili_session_pick_mode": cfg.get("bili_session_pick_mode"),
        "bili_session_cooldown_seconds": cfg.get("bili_session_cooldown_seconds"),
        "admin_scan_summary_interval_seconds": cfg.get("admin_scan_summary_interval_seconds"),
        "api_request_mode": cfg.get("api_request_mode"),
        "scan_timeout_seconds": cfg.get("scan_timeout_seconds"),
        "admin_telegram_ids": cfg.get("admin_telegram_ids") or [],
        "bot_id": cfg.get("telegram", {}).get("bot_id"),
    }


def get_public_account_settings() -> Dict[str, Any]:
    now = time.monotonic()
    with _PUBLIC_ACCOUNT_SETTINGS_CACHE_LOCK:
        cached_value = _PUBLIC_ACCOUNT_SETTINGS_CACHE.get("value")
        expires_at = float(_PUBLIC_ACCOUNT_SETTINGS_CACHE.get("expires_at", 0.0) or 0.0)
        if isinstance(cached_value, dict) and now < expires_at:
            return dict(cached_value)

    cfg = load_runtime_config()
    value = {
        "interval": cfg.get("interval", 20),
        "cloudflare_validation_enabled": bool(cfg.get("cloudflare_validation_enabled", False)),
        "cloudflare_turnstile_site_key": str(cfg.get("cloudflare_turnstile_site_key") or ""),
    }
    with _PUBLIC_ACCOUNT_SETTINGS_CACHE_LOCK:
        _PUBLIC_ACCOUNT_SETTINGS_CACHE["value"] = dict(value)
        _PUBLIC_ACCOUNT_SETTINGS_CACHE["expires_at"] = now + _PUBLIC_ACCOUNT_SETTINGS_CACHE_TTL_SECONDS
    return value


def reset_public_account_settings_cache() -> None:
    with _PUBLIC_ACCOUNT_SETTINGS_CACHE_LOCK:
        _PUBLIC_ACCOUNT_SETTINGS_CACHE["value"] = None
        _PUBLIC_ACCOUNT_SETTINGS_CACHE["expires_at"] = 0.0


def get_telegram_bot_id() -> str:
    cfg = load_runtime_config()
    return str(cfg.get("telegram", {}).get("bot_id") or "")

def list_access_users(status: Optional[str] = None) -> List[Dict[str, Any]]:
    from . import db

    _migrate_yaml_users_to_db_if_needed()
    return db.list_access_users(status=status)

def get_access_user(username: str) -> Optional[Dict[str, Any]]:
    from . import db

    _migrate_yaml_users_to_db_if_needed()

    username = (username or "").strip()
    if not username:
        return None

    now = time.monotonic()
    with _ACCESS_USER_CACHE_LOCK:
        entry = _ACCESS_USER_CACHE.get(username)
        if entry is not None and now < entry.get("expires_at", 0.0):
            value = entry.get("value")
            return dict(value) if value is not None else None

    user = db.get_access_user(username)
    with _ACCESS_USER_CACHE_LOCK:
        _ACCESS_USER_CACHE[username] = {
            "value": dict(user) if user is not None else None,
            "expires_at": now + _ACCESS_USER_CACHE_TTL_SECONDS,
        }
    return user

def get_access_user_by_telegram_id(telegram_id: str) -> Optional[Dict[str, Any]]:
    if not telegram_id:
        return None
    users = list_access_users(status="active")
    for user in users:
        if str(telegram_id) in (user.get("telegram_ids") or []):
            return user
    return None

def upsert_access_user(
    username: str,
    display_name: str = "",
    password_hash: str = "",
    telegram_ids: Optional[Iterable[str]] = None,
    keywords: Optional[Iterable[str]] = None,
    roles: Optional[Iterable[str]] = None,
    status: str = "active",
    notify_enabled: bool = True,
) -> None:
    from . import db

    _migrate_yaml_users_to_db_if_needed()
    db.upsert_access_user(
        username=username,
        display_name=display_name,
        password_hash=password_hash,
        telegram_ids=_normalize_string_list(telegram_ids),
        keywords=_normalize_string_list(keywords),
        roles=_normalize_string_list(roles),
        status=status,
        notify_enabled=notify_enabled,
    )
    _invalidate_access_user_cache(username)

def delete_access_user(username: str) -> None:
    from . import db

    _migrate_yaml_users_to_db_if_needed()
    db.delete_access_user(username)
    _invalidate_access_user_cache(username)


def _invalidate_access_user_cache(username: str) -> None:
    with _ACCESS_USER_CACHE_LOCK:
        _ACCESS_USER_CACHE.pop((username or "").strip(), None)


def reset_access_user_cache() -> None:
    with _ACCESS_USER_CACHE_LOCK:
        _ACCESS_USER_CACHE.clear()

def list_access_users_with_telegram(status: Optional[str] = "active") -> List[Dict[str, Any]]:
    users = list_access_users(status=status)
    return [user for user in users if user.get("telegram_ids")]


def set_mode(mode: str) -> bool:
    if mode not in ("latest", "continue", "continue_until_repeat"):
        return False
    save_yaml_config_value("scan_mode", mode)
    reset_public_account_settings_cache()
    return True
