import gzip
import base64
import json
import os
import re
import threading
import time
import urllib.parse
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

import sqlalchemy as sa
from sqlalchemy import and_, case, create_engine, delete, event, func, literal, or_, select, true
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, aliased, sessionmaker
from .env import data_dir, env_int, env_str, load_dotenv, resolve_project_path
from .passwords import hash_password, is_password_hash
from .orm_models import (
    AccessUser,
    Base,
    BiliSession,
    C2CItem,
    C2CItemSnapshot,
    Product,
)


_BACKEND_CACHE_LOCK = threading.Lock()
_BACKEND_INSTANCE: Optional["SqlalchemyBackend"] = None
_BACKEND_CACHE_KEY: Tuple[str, str] = ("", "")
_DB_REQUEST_TRACE: ContextVar[Optional[Dict[str, float]]] = ContextVar(
    "bsm_db_request_trace",
    default=None,
)


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        return default
    return parsed if parsed > 0 else default


def _now() -> str:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(now.microsecond / 1000):03d}Z"


def _utc_cutoff(*, seconds: int = 0, hours: int = 0, days: int = 0) -> str:
    from datetime import datetime, timedelta, timezone

    dt = datetime.now(timezone.utc) - timedelta(seconds=seconds, hours=hours, days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(dt.microsecond / 1000):03d}Z"


def _snapshot_now() -> str:
    """Use millisecond precision timestamp in UTC."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(now.microsecond / 1000):03d}Z"


def _load_bili_session_runtime_settings() -> Dict[str, Any]:
    from .settings import load_runtime_config

    cfg = load_runtime_config()
    mode = str(cfg.get("bili_session_pick_mode") or "round_robin").strip().lower()
    if mode not in {"round_robin", "random"}:
        mode = "round_robin"
    cooldown_seconds = cfg.get("bili_session_cooldown_seconds", 60)
    try:
        cooldown_seconds = int(cooldown_seconds)
    except Exception:
        cooldown_seconds = 60
    if cooldown_seconds < 0:
        cooldown_seconds = 60
    return {
        "mode": mode,
        "cooldown_seconds": cooldown_seconds,
    }


def _available_bili_session_condition(cooldown_seconds: int) -> Any:
    if cooldown_seconds <= 0:
        return true()
    cutoff = _utc_cutoff(seconds=cooldown_seconds)
    return or_(
        BiliSession.last_error.is_(None),
        BiliSession.last_checked_at.is_(None),
        BiliSession.last_checked_at <= cutoff,
    )

def _data_dir() -> str:
    return data_dir()


def _default_db_path() -> str:
    if os.environ.get("BSM_TESTING") == "1":
        return os.path.join(_data_dir(), "test_scan.db")
    return os.path.join(_data_dir(), "scan.db")


def _sqlite_url(path_value: str) -> str:
    path = Path(path_value).expanduser()
    if path.is_absolute():
        return f"sqlite:///{path}"
    return f"sqlite:///{path.as_posix()}"


def _load_db_settings() -> Dict[str, Any]:
    from .settings import load_yaml_config

    load_dotenv()
    yaml_config = load_yaml_config()
    testing = env_str("BSM_TESTING", "0") == "1"
    explicit_db_path = env_str("BSM_DB_PATH", "")
    explicit_test_path = env_str("BSM_TEST_DB_PATH", "")
    sqlite_path = (
        explicit_db_path
        or (explicit_test_path if testing else None)
        or resolve_project_path(env_str("BSM_SQLITE_PATH", ""))
        or _default_db_path()
    )
    if testing and not explicit_db_path:
        sqlite_path = (
            explicit_test_path
            or resolve_project_path(env_str("BSM_SQLITE_TEST_PATH", ""))
            or os.path.join(_data_dir(), "test_scan.db")
        )

    backend = env_str("BSM_DB_BACKEND", "sqlite").strip().lower()
    account_id = env_str("BSM_CF_ACCOUNT_ID", "")
    database_id = env_str("BSM_CF_DATABASE_ID", "")
    api_token = env_str("BSM_CF_API_TOKEN", "")
    if backend == "cloudflare":
        db_url = (
            "cloudflare_d1://"
            f"{urllib.parse.quote_plus(account_id)}:"
            f"{urllib.parse.quote_plus(api_token)}@"
            f"{urllib.parse.quote_plus(database_id)}"
        )
    else:
        db_url = _sqlite_url(sqlite_path)

    return {
        "backend": backend,
        "sqlite_path": sqlite_path,
        "db_url": db_url,
        "cloudflare_account_id": account_id,
        "cloudflare_database_id": database_id,
        "cloudflare_api_token": api_token,
        "cloudflare_timeout": env_int("BSM_CF_TIMEOUT", 15),
    }


def get_db_backend_name() -> str:
    return str(_load_db_settings().get("backend", "sqlite"))


@dataclass
class DatabaseBackend:
    def ensure_schema(self) -> None:
        raise NotImplementedError


@dataclass
class SqlalchemyBackend(DatabaseBackend):
    db_url: str
    sqlite_path: str = ""
    _engine: Engine = field(init=False, repr=False)
    _session_factory: sessionmaker[Session] = field(init=False, repr=False)
    _schema_ready: bool = field(init=False, default=False, repr=False)
    _schema_lock: threading.Lock = field(
        init=False,
        default_factory=threading.Lock,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if self.sqlite_path:
            dir_name = os.path.dirname(self.sqlite_path)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)
        connect_args = {"check_same_thread": False} if self.db_url.startswith("sqlite:///") else {}
        self._engine = create_engine(
            self.db_url,
            connect_args=connect_args,
            pool_pre_ping=not self._is_sqlite(),
        )
        if self._is_sqlite():
            @event.listens_for(self._engine, "connect")
            def _enable_sqlite_fk(dbapi_connection: Any, connection_record: Any) -> None:
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys = ON")
                cursor.close()
        else:
            @event.listens_for(self._engine, "before_cursor_execute")
            def _before_cursor_execute(
                conn: Any,
                cursor: Any,
                statement: str,
                parameters: Any,
                context: Any,
                executemany: bool,
            ) -> None:
                context._bsm_started_at = time.perf_counter()

            @event.listens_for(self._engine, "after_cursor_execute")
            def _after_cursor_execute(
                conn: Any,
                cursor: Any,
                statement: str,
                parameters: Any,
                context: Any,
                executemany: bool,
            ) -> None:
                started_at = getattr(context, "_bsm_started_at", None)
                if started_at is None:
                    return
                record_db_request_trace((time.perf_counter() - started_at) * 1000.0)
        self._session_factory = sessionmaker(bind=self._engine, expire_on_commit=False)

    def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            self._ensure_schema_once()
            self._schema_ready = True

    def _ensure_schema_once(self) -> None:
        with self._engine.begin() as conn:
            Base.metadata.create_all(bind=conn)
            inspector = sa.inspect(conn)
            item_columns = {column["name"] for column in inspector.get_columns("c2c_items")}
            if "category_id" not in item_columns:
                conn.execute(sa.text("ALTER TABLE c2c_items ADD COLUMN category_id TEXT"))
            if "detail_blob" not in item_columns:
                conn.execute(sa.text("ALTER TABLE c2c_items ADD COLUMN detail_blob BLOB"))

    def _is_sqlite(self) -> bool:
        return self.db_url.startswith("sqlite:///")

    @contextmanager
    def session(self) -> Iterator[Session]:
        self.ensure_schema()
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def _backend() -> DatabaseBackend:
    global _BACKEND_INSTANCE, _BACKEND_CACHE_KEY
    settings = _load_db_settings()
    sqlite_path = settings["sqlite_path"] if settings["backend"] == "sqlite" else ""
    cache_key = (settings["db_url"], sqlite_path)
    with _BACKEND_CACHE_LOCK:
        if _BACKEND_INSTANCE is None or _BACKEND_CACHE_KEY != cache_key:
            _BACKEND_INSTANCE = SqlalchemyBackend(
                db_url=settings["db_url"],
                sqlite_path=sqlite_path,
            )
            _BACKEND_CACHE_KEY = cache_key
        return _BACKEND_INSTANCE


def _reset_backend_cache() -> None:
    global _BACKEND_INSTANCE, _BACKEND_CACHE_KEY
    with _BACKEND_CACHE_LOCK:
        backend = _BACKEND_INSTANCE
        if backend is not None:
            backend._engine.dispose()
        _BACKEND_INSTANCE = None
        _BACKEND_CACHE_KEY = ("", "")


def begin_db_request_trace() -> None:
    _DB_REQUEST_TRACE.set({"count": 0.0, "total_ms": 0.0})


def record_db_request_trace(duration_ms: float) -> None:
    trace = _DB_REQUEST_TRACE.get()
    if trace is None:
        return
    trace["count"] = trace.get("count", 0.0) + 1.0
    trace["total_ms"] = trace.get("total_ms", 0.0) + duration_ms


def end_db_request_trace() -> Dict[str, float]:
    trace = _DB_REQUEST_TRACE.get()
    _DB_REQUEST_TRACE.set(None)
    if trace is None:
        return {"count": 0.0, "total_ms": 0.0}
    return {
        "count": float(trace.get("count", 0.0)),
        "total_ms": float(trace.get("total_ms", 0.0)),
    }


def _sanitize_str(val: Any) -> str:
    if not isinstance(val, str):
        return ""
    return val.strip().strip("`")


_DEFAULT_NOFACE_URL = "https://i0.hdslb.com/bfs/face/member/noface.jpg"


def _normalize_uface(val: Any) -> str:
    text = _sanitize_str(val)
    if not text:
        return ""
    if text == _DEFAULT_NOFACE_URL:
        return ""
    return text


def _serialize_uface(val: Any) -> str:
    """Always return a usable avatar URL in API responses."""
    normalized = _normalize_uface(val)
    return normalized or _DEFAULT_NOFACE_URL


def _json_list(value: Any) -> List[str]:
    if isinstance(value, list):
        raw = value
    elif value is None:
        raw = []
    else:
        try:
            parsed = json.loads(str(value))
        except Exception:
            parsed = []
        raw = parsed if isinstance(parsed, list) else []
    result: List[str] = []
    seen = set()
    for item in raw:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _placeholders(size: int) -> str:
    return ",".join(["?"] * max(0, size))


def _require_sqlalchemy_backend() -> "SqlalchemyBackend":
    backend = _backend()
    if not isinstance(backend, SqlalchemyBackend):
        raise TypeError("Unsupported database backend")
    return backend


def _bili_session_to_dict(row: BiliSession) -> Dict[str, Any]:
    return {
        "id": row.id,
        "login_username": row.login_username,
        "cookies": row.cookies,
        "created_by": row.created_by,
        "status": row.status,
        "fetch_count": int(row.fetch_count or 0),
        "login_at": row.login_at,
        "last_success_fetch_at": row.last_success_fetch_at,
        "last_used_at": row.last_used_at,
        "last_checked_at": row.last_checked_at,
        "last_error": row.last_error,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _access_user_to_dict(row: AccessUser) -> Dict[str, Any]:
    return {
        "id": row.id,
        "username": row.username,
        "display_name": row.display_name or "",
        "password_hash": row.password_hash or "",
        "telegram_ids": _json_list(row.telegram_ids_json),
        "keywords": _json_list(row.keywords_json),
        "roles": _json_list(row.roles_json),
        "notify_enabled": bool(row.notify_enabled),
        "status": row.status or "active",
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _encode_detail_blob(detail_list: List[Dict[str, Any]]) -> bytes:
    raw = json.dumps(detail_list, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return gzip.compress(raw, compresslevel=6)


def _normalize_detail_payload(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("detailDtoList", "detail_list", "details", "items", "list"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        data = payload.get("data")
        if isinstance(data, dict):
            for key in ("detailDtoList", "detail_list", "details", "items", "list"):
                value = data.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
    return []


def _decode_detail_blob(detail_blob: Any) -> List[Dict[str, Any]]:
    if not detail_blob:
        return []
    parsed, _ = _decode_detail_blob_with_reason(detail_blob)
    return parsed


def _decode_detail_blob_with_reason(detail_blob: Any) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    if not detail_blob:
        return [], "blob_empty"

    blob_bytes: Optional[bytes] = None
    if isinstance(detail_blob, memoryview):
        blob_bytes = detail_blob.tobytes()
    elif isinstance(detail_blob, (bytes, bytearray)):
        blob_bytes = bytes(detail_blob)
    elif isinstance(detail_blob, str):
        text = detail_blob.strip()
        if not text:
            return [], "blob_text_empty"
        # Case 1: plain JSON string
        try:
            parsed = json.loads(text)
            normalized = _normalize_detail_payload(parsed)
            if normalized:
                return normalized, None
        except Exception:
            pass
        # Case 2: base64(gzip(json))
        try:
            blob_bytes = base64.b64decode(text, validate=False)
        except Exception:
            blob_bytes = text.encode("utf-8", errors="ignore")
    else:
        try:
            blob_bytes = bytes(detail_blob)
        except Exception:
            return [], f"blob_bytes_convert_failed:{type(detail_blob).__name__}"

    if blob_bytes is None:
        return [], "blob_bytes_none"

    try:
        parsed = json.loads(gzip.decompress(blob_bytes).decode("utf-8"))
        normalized = _normalize_detail_payload(parsed)
        if normalized:
            return normalized, None
    except Exception:
        pass
    # Some deployments store base64(gzip(json)) as ASCII bytes in BLOB/TEXT.
    try:
        text = blob_bytes.decode("ascii").strip()
        if text:
            decoded_b64 = base64.b64decode(text, validate=False)
            try:
                parsed = json.loads(gzip.decompress(decoded_b64).decode("utf-8"))
                normalized = _normalize_detail_payload(parsed)
                if normalized:
                    return normalized, None
            except Exception:
                pass
            try:
                parsed = json.loads(decoded_b64.decode("utf-8"))
                normalized = _normalize_detail_payload(parsed)
                if normalized:
                    return normalized, None
            except Exception:
                pass
    except Exception:
        pass
    try:
        parsed = json.loads(blob_bytes.decode("utf-8"))
        normalized = _normalize_detail_payload(parsed)
        if normalized:
            return normalized, None
        return [], f"blob_json_unrecognized_shape:{type(parsed).__name__}"
    except Exception:
        return [], "blob_decode_failed"


def _decode_detail_json_text(detail_json: Any) -> List[Dict[str, Any]]:
    if detail_json is None:
        return []
    try:
        text = str(detail_json)
    except Exception:
        return []
    if not text.strip():
        return []
    try:
        parsed = json.loads(text)
    except Exception:
        return []
    normalized = _normalize_detail_payload(parsed)
    return normalized if normalized else []


def _extract_img_from_detail_items(data: Any) -> str:
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            for key in ("img", "imgUrl", "image"):
                val = first.get(key)
                if val and isinstance(val, str) and val.strip():
                    return val.strip()
    return ""


def _extract_img_from_products(data: Any) -> str:
    if not isinstance(data, list):
        return ""
    for item in data:
        if not isinstance(item, dict):
            continue
        for key in ("imgUrl", "img", "image"):
            val = item.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return ""


def _detail_item_merge_key(item: Dict[str, Any]) -> Tuple[Any, Any, Any]:
    items_id = item.get("itemsId")
    sku_id = item.get("skuId")
    blindbox_id = item.get("blindBoxId")
    if blindbox_id is None:
        blindbox_id = item.get("blindboxId")
    return (items_id, sku_id, blindbox_id)


def _merge_detail_list_with_existing(
    incoming_list: List[Dict[str, Any]],
    existing_list: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not incoming_list:
        return []
    existing_map: Dict[Tuple[Any, Any, Any], Dict[str, Any]] = {}
    for old_item in existing_list:
        if not isinstance(old_item, dict):
            continue
        existing_map[_detail_item_merge_key(old_item)] = old_item

    merged: List[Dict[str, Any]] = []
    seen_keys: set[Tuple[Any, Any, Any]] = set()
    for new_item in incoming_list:
        if not isinstance(new_item, dict):
            continue
        key = _detail_item_merge_key(new_item)
        old_item = existing_map.get(key, {})
        merged_item = dict(old_item)
        merged_item.update(new_item)
        merged.append(merged_item)
        seen_keys.add(key)
    # Keep existing detail rows not present in the incoming partial payload.
    for old_item in existing_list:
        if not isinstance(old_item, dict):
            continue
        key = _detail_item_merge_key(old_item)
        if key in seen_keys:
            continue
        merged.append(dict(old_item))
    return merged


def _market_item_to_dict(
    row: C2CItem,
    recent_listed_count: int = 0,
    bundled_items: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    normalized_bundled_items = bundled_items if isinstance(bundled_items, list) else []
    return {
        "id": row.c2c_items_id,
        "category_id": row.category_id,
        "name": row.c2c_items_name,
        "show_price": row.show_price,
        "show_market_price": row.show_market_price,
        "uface": _serialize_uface(row.uface),
        "uname": row.uname,
        "img_url": _extract_img_from_products(normalized_bundled_items),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "recent_listed_count": recent_listed_count,
        "bundled_items": normalized_bundled_items,
        "publish_status": row.publish_status,
        "sale_status": row.sale_status,
        "drop_reason": row.drop_reason,
    }


def _load_current_details_for_c2c_ids(c2c_items_ids: Sequence[int]) -> Dict[int, List[Dict[str, Any]]]:
    if not c2c_items_ids:
        return {}
    backend = _require_sqlalchemy_backend()
    current_details = _current_item_details_subquery("market_item_details_for_ids")
    with backend.session() as session:
        rows = session.execute(
            select(
                current_details.c.c2c_items_id,
                current_details.c.items_id,
                current_details.c.sku_id,
                current_details.c.name,
                current_details.c.img_url,
                current_details.c.market_price,
                current_details.c.id,
            )
            .where(current_details.c.c2c_items_id.in_(list(c2c_items_ids)))
            .order_by(current_details.c.c2c_items_id.asc(), current_details.c.id.asc())
        ).all()

    result: Dict[int, List[Dict[str, Any]]] = {}
    for row in rows:
        cid = int(row.c2c_items_id)
        if cid not in result:
            result[cid] = []
        result[cid].append(
            {
                "itemsId": int(row.items_id) if row.items_id is not None else 0,
                "skuId": int(row.sku_id) if row.sku_id is not None else 0,
                "blindBoxId": None,
                "blindboxId": None,
                "name": row.name or "",
                "imgUrl": row.img_url or "",
                "img": row.img_url or "",
                "image": row.img_url or "",
                "marketPrice": int(row.market_price) if row.market_price is not None else None,
            }
        )
    return result


def _latest_snapshot_subquery(name: str = "latest_snapshot"):
    return (
        select(
            C2CItemSnapshot.c2c_items_id.label("c2c_items_id"),
            func.max(C2CItemSnapshot.snapshot_at).label("snapshot_at"),
        )
        .group_by(C2CItemSnapshot.c2c_items_id)
        .subquery(name)
    )


def _current_item_details_subquery(name: str = "current_item_details"):
    latest_snapshot = _latest_snapshot_subquery(f"{name}_latest")
    return (
        select(
            C2CItemSnapshot.id.label("id"),
            C2CItemSnapshot.c2c_items_id.label("c2c_items_id"),
            Product.items_id.label("items_id"),
            Product.sku_id.label("sku_id"),
            Product.name.label("name"),
            Product.img_url.label("img_url"),
            Product.market_price.label("market_price"),
            C2CItemSnapshot.est_price.label("est_price"),
            C2CItemSnapshot.snapshot_at.label("snapshot_at"),
        )
        .join(Product, Product.id == C2CItemSnapshot.product_id)
        .join(
            latest_snapshot,
            and_(
                C2CItemSnapshot.c2c_items_id == latest_snapshot.c.c2c_items_id,
                C2CItemSnapshot.snapshot_at == latest_snapshot.c.snapshot_at,
            ),
        )
        .subquery(name)
    )


def _market_recent_listing_count_expr(cutoff: Optional[str] = None):
    cutoff_value = cutoff or _utc_cutoff(days=15)
    recent_item = aliased(C2CItem)
    current_details = _current_item_details_subquery("market_recent_current_details")
    primary_items_sq = (
        select(func.min(current_details.c.items_id))
        .where(current_details.c.c2c_items_id == C2CItem.c2c_items_id)
        .correlate(C2CItem)
        .scalar_subquery()
    )
    primary_sku_sq = (
        select(current_details.c.sku_id)
        .where(current_details.c.c2c_items_id == C2CItem.c2c_items_id)
        .order_by(current_details.c.id.asc())
        .limit(1)
        .correlate(C2CItem)
        .scalar_subquery()
    )
    return (
        select(func.count(func.distinct(current_details.c.c2c_items_id)))
        .select_from(current_details)
        .join(recent_item, recent_item.c2c_items_id == current_details.c.c2c_items_id)
        .where(current_details.c.items_id == primary_items_sq)
        .where(current_details.c.sku_id == primary_sku_sq)
        .where(recent_item.updated_at >= cutoff_value)
        .correlate(C2CItem)
        .scalar_subquery()
    )


def _market_page_order_clauses(sort_by: str):
    created_or_updated = func.coalesce(C2CItem.created_at, C2CItem.updated_at)
    if sort_by == "TIME_DESC":
        return (created_or_updated.desc(), C2CItem.c2c_items_id.desc())
    if sort_by == "TIME_ASC":
        return (created_or_updated.asc(), C2CItem.c2c_items_id.asc())
    if sort_by == "ID_ASC":
        return (C2CItem.c2c_items_id.asc(),)
    if sort_by == "ID_DESC":
        return (C2CItem.c2c_items_id.desc(),)
    if sort_by == "PRICE_ASC":
        return (C2CItem.price.asc(), created_or_updated.desc())
    if sort_by == "PRICE_DESC":
        return (C2CItem.price.desc(), created_or_updated.desc())
    # Default market ordering follows creation timestamp (created_at) descending.
    return (created_or_updated.desc(), C2CItem.c2c_items_id.desc())


def _recent_listing_page_order_clauses(numbered_rows, sort_by: str):
    created_or_updated = func.coalesce(numbered_rows.c.created_at, numbered_rows.c.updated_at)
    if sort_by == "TIME_DESC":
        return (created_or_updated.desc(), numbered_rows.c.c2c_items_id.desc())
    if sort_by == "TIME_ASC":
        return (created_or_updated.asc(), numbered_rows.c.c2c_items_id.asc())
    if sort_by == "ID_ASC":
        return (numbered_rows.c.c2c_items_id.asc(),)
    if sort_by == "ID_DESC":
        return (numbered_rows.c.c2c_items_id.desc(),)
    if sort_by == "PRICE_ASC":
        return (numbered_rows.c.est_price.asc(), created_or_updated.desc())
    if sort_by == "PRICE_DESC":
        return (numbered_rows.c.est_price.desc(), created_or_updated.desc())
    return (created_or_updated.desc(), numbered_rows.c.c2c_items_id.desc())


def _load_market_items_page(
    *,
    page: int,
    limit: int,
    sort_by: str,
    time_filter_hours: int,
    keyword: Optional[str] = None,
    category_ids: Optional[Sequence[str]] = None,
) -> Tuple[List[Dict[str, Any]], int, int]:
    backend = _require_sqlalchemy_backend()
    limit = max(1, limit)
    page = max(1, page)
    offset = (page - 1) * limit
    order_clauses = _market_page_order_clauses(sort_by)

    base_stmt = select(
        C2CItem.c2c_items_id.label("c2c_items_id"),
        func.row_number().over(order_by=order_clauses).label("row_num"),
        func.count().over().label("total_count"),
    )

    if keyword is not None:
        base_stmt = base_stmt.where(C2CItem.c2c_items_name.like(f"%{keyword}%"))

    normalized_category_ids = [str(item).strip() for item in (category_ids or []) if str(item).strip()]
    if normalized_category_ids:
        base_stmt = base_stmt.where(C2CItem.category_id.in_(normalized_category_ids))

    if time_filter_hours > 0:
        cutoff = _utc_cutoff(hours=time_filter_hours)
        base_stmt = base_stmt.where(C2CItem.updated_at >= cutoff)

    filtered_cte = base_stmt.cte("filtered_market_items")
    totals_cte = (
        select(func.max(filtered_cte.c.total_count).label("total_count"))
        .select_from(filtered_cte)
        .cte("market_item_totals")
    )
    paged_cte = (
        select(filtered_cte.c.c2c_items_id, filtered_cte.c.row_num)
        .where(filtered_cte.c.row_num > offset)
        .where(filtered_cte.c.row_num <= offset + limit)
        .cte("paged_market_items")
    )

    with backend.session() as session:
        rows = session.execute(
            select(
                C2CItem,
                func.coalesce(totals_cte.c.total_count, 0).label("total_count"),
            )
            .select_from(totals_cte)
            .outerjoin(paged_cte, true())
            .outerjoin(C2CItem, C2CItem.c2c_items_id == paged_cte.c.c2c_items_id)
            .order_by(paged_cte.c.row_num.asc())
        ).all()

    total_count = int(rows[0].total_count) if rows else 0
    total_pages = (total_count + limit - 1) // limit if total_count > 0 else 0

    # Batch-fetch listing counts for just this page (separate, simpler query)
    page_ids = [int(row[0].c2c_items_id) for row in rows if row[0] is not None]
    listing_counts = get_15d_listing_counts_batch(page_ids) if page_ids else {}

    details_map = _load_current_details_for_c2c_ids(page_ids) if page_ids else {}

    items = []
    for row in rows:
        if row[0] is None:
            continue
        cid = int(row[0].c2c_items_id)
        items.append(
            _market_item_to_dict(
                row[0],
                listing_counts.get(cid, 0),
                details_map.get(cid, []),
            )
        )
    return items, total_count, total_pages


def _load_recent_15d_listings_page(
    *,
    items_id_expr,
    sku_id_expr=None,
    page: int,
    limit: int,
    sort_by: str,
) -> Tuple[Optional[int], List[Dict[str, Any]], int, int]:
    backend = _require_sqlalchemy_backend()
    limit = max(1, limit)
    page = max(1, page)
    offset = (page - 1) * limit
    cutoff = _utc_cutoff(days=15)
    items_id_sql = items_id_expr if hasattr(items_id_expr, "label") else literal(items_id_expr)
    sku_id_sql = None
    if sku_id_expr is not None:
        sku_id_sql = sku_id_expr if hasattr(sku_id_expr, "label") else literal(sku_id_expr)
    current_details = _current_item_details_subquery("recent_listing_current_details")
    grouped_stmt = (
        select(
            C2CItem.c2c_items_id.label("c2c_items_id"),
            C2CItem.c2c_items_name.label("name"),
            C2CItem.show_price.label("show_price"),
            C2CItem.show_market_price.label("show_market_price"),
            C2CItem.uface.label("uface"),
            C2CItem.uname.label("uname"),
            C2CItem.created_at.label("created_at"),
            C2CItem.updated_at.label("updated_at"),
            C2CItem.publish_status.label("publish_status"),
            C2CItem.sale_status.label("sale_status"),
            C2CItem.drop_reason.label("drop_reason"),
            func.min(current_details.c.est_price).label("est_price"),
        )
        .join(current_details, current_details.c.c2c_items_id == C2CItem.c2c_items_id)
        .where(current_details.c.items_id == items_id_sql)
        .where(C2CItem.updated_at >= cutoff)
    )
    if sku_id_sql is not None:
        grouped_stmt = grouped_stmt.where(current_details.c.sku_id == sku_id_sql)
    grouped_rows = grouped_stmt.group_by(
        C2CItem.c2c_items_id,
        C2CItem.c2c_items_name,
        C2CItem.show_price,
        C2CItem.show_market_price,
        C2CItem.uface,
        C2CItem.uname,
        C2CItem.created_at,
        C2CItem.updated_at,
        C2CItem.publish_status,
        C2CItem.sale_status,
        C2CItem.drop_reason,
    ).subquery()
    order_clauses = _recent_listing_page_order_clauses(grouped_rows, sort_by)
    numbered_rows = (
        select(
            grouped_rows,
            func.row_number().over(order_by=order_clauses).label("row_num"),
            func.count().over().label("total_count"),
        ).subquery()
    )
    totals_cte = (
        select(func.max(numbered_rows.c.total_count).label("total_count"))
        .select_from(numbered_rows)
        .cte("recent_listing_totals")
    )
    paged_rows = (
        select(numbered_rows)
        .where(numbered_rows.c.row_num > offset)
        .where(numbered_rows.c.row_num <= offset + limit)
        .cte("paged_recent_listings")
    )

    with backend.session() as session:
        rows = session.execute(
            select(
                items_id_sql.label("items_id"),
                func.coalesce(totals_cte.c.total_count, 0).label("total_count"),
                paged_rows.c.c2c_items_id,
                paged_rows.c.name,
                paged_rows.c.show_price,
                paged_rows.c.show_market_price,
                paged_rows.c.uface,
                paged_rows.c.uname,
                paged_rows.c.created_at,
                paged_rows.c.updated_at,
                paged_rows.c.publish_status,
                paged_rows.c.sale_status,
                paged_rows.c.drop_reason,
                paged_rows.c.est_price,
                paged_rows.c.row_num,
            )
            .select_from(totals_cte)
            .outerjoin(paged_rows, true())
            .order_by(paged_rows.c.row_num.asc())
        ).all()

    resolved_items_id = int(rows[0].items_id) if rows and rows[0].items_id is not None else None
    total_count = int(rows[0].total_count) if rows else 0
    total_pages = (total_count + limit - 1) // limit if total_count > 0 else 0
    listing_ids = [int(row.c2c_items_id) for row in rows if row.c2c_items_id is not None]
    details_map = _load_current_details_for_c2c_ids(listing_ids) if listing_ids else {}

    listings: List[Dict[str, Any]] = []
    for row in rows:
        if row.c2c_items_id is None:
            continue
        bundled_items = details_map.get(int(row.c2c_items_id), [])
        est_price = row.est_price
        listings.append(
            {
                "c2c_items_id": row.c2c_items_id,
                "name": row.name,
                "show_price": row.show_price,
                "show_market_price": row.show_market_price,
                "uface": _serialize_uface(row.uface),
                "uname": row.uname,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "bundled_items": bundled_items,
                "publish_status": row.publish_status,
                "sale_status": row.sale_status,
                "drop_reason": row.drop_reason,
                "est_price": est_price,
                "show_est_price": f"{int(est_price or 0) / 100:.2f}" if est_price is not None else None,
            }
        )
    return resolved_items_id, listings, total_count, total_pages


def ping_database() -> None:
    backend = _require_sqlalchemy_backend()
    with backend.session() as session:
        session.scalar(select(1))


def get_database_size_report(days: int = 7, top_n: int = 20) -> Dict[str, Any]:
    backend = _require_sqlalchemy_backend()
    engine = backend._engine
    inspector = sa.inspect(engine)
    dialect = str(engine.dialect.name or "").lower()
    backend_name = get_db_backend_name()
    days = max(1, min(int(days or 7), 3650))
    top_n = max(1, min(int(top_n or 20), 200))

    tables = sorted(inspector.get_table_names())
    utc_now = datetime.now(timezone.utc)
    cutoff = (utc_now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    generated_at = utc_now.strftime("%Y-%m-%dT%H:%M:%SZ")
    identifier_preparer = engine.dialect.identifier_preparer

    sqlite_total_bytes: Optional[int] = None
    sqlite_used_bytes: Optional[int] = None
    sqlite_free_bytes: Optional[int] = None
    sqlite_wal_bytes = 0
    sqlite_dbstat_map: Dict[str, int] = {}
    postgres_total_bytes: Optional[int] = None
    skipped_tables: List[str] = []
    warnings: List[str] = []

    with engine.connect() as conn:
        if dialect == "sqlite":
            if backend.sqlite_path:
                db_path = Path(backend.sqlite_path)
                if db_path.exists():
                    sqlite_total_bytes = int(db_path.stat().st_size)
                wal_path = Path(f"{backend.sqlite_path}-wal")
                if wal_path.exists():
                    sqlite_wal_bytes = int(wal_path.stat().st_size)
            try:
                page_size = int(conn.execute(sa.text("PRAGMA page_size")).scalar() or 0)
                page_count = int(conn.execute(sa.text("PRAGMA page_count")).scalar() or 0)
                freelist_count = int(conn.execute(sa.text("PRAGMA freelist_count")).scalar() or 0)
                if page_size > 0 and page_count >= 0 and freelist_count >= 0:
                    sqlite_used_bytes = max(0, (page_count - freelist_count) * page_size)
                    sqlite_free_bytes = max(0, freelist_count * page_size)
            except Exception:
                sqlite_used_bytes = None
                sqlite_free_bytes = None
            try:
                rows = conn.execute(sa.text("SELECT name, SUM(pgsize) AS total_bytes FROM dbstat GROUP BY name")).all()
                for row in rows:
                    name = str(row[0] or "").strip()
                    if not name:
                        continue
                    sqlite_dbstat_map[name] = int(row[1] or 0)
            except Exception:
                sqlite_dbstat_map = {}
                try:
                    conn.execute(sa.text("CREATE VIRTUAL TABLE temp.bsm_dbstat USING dbstat(main)"))
                    rows = conn.execute(sa.text("SELECT name, SUM(pgsize) AS total_bytes FROM temp.bsm_dbstat GROUP BY name")).all()
                    for row in rows:
                        name = str(row[0] or "").strip()
                        if not name:
                            continue
                        sqlite_dbstat_map[name] = int(row[1] or 0)
                except Exception:
                    sqlite_dbstat_map = {}
        elif dialect == "postgresql":
            postgres_total_bytes = int(conn.execute(sa.text("SELECT pg_database_size(current_database())")).scalar() or 0)

        table_rows: List[Dict[str, Any]] = []
        for table_name in tables:
            # Cloudflare D1 may expose internal tables (e.g. _cf_KV) that are not readable.
            if backend_name == "cloudflare" and table_name.startswith("_cf_"):
                skipped_tables.append(table_name)
                continue
            if table_name.startswith("sqlite_"):
                skipped_tables.append(table_name)
                continue

            quoted_table = identifier_preparer.quote(table_name)
            try:
                row_count = int(conn.execute(sa.text(f"SELECT COUNT(*) FROM {quoted_table}")).scalar() or 0)
                columns = {str(col.get("name") or "") for col in inspector.get_columns(table_name)}
            except SQLAlchemyError as exc:
                skipped_tables.append(table_name)
                warnings.append(f"skip table {table_name}: {exc.__class__.__name__}")
                continue
            except Exception as exc:
                skipped_tables.append(table_name)
                warnings.append(f"skip table {table_name}: {exc.__class__.__name__}")
                continue
            recent_rows: Optional[int] = None
            if table_name == "c2c_items_snapshot":
                try:
                    if dialect == "sqlite":
                        recent_rows = int(
                            conn.execute(
                                sa.text(
                                    """
                                    SELECT COUNT(*)
                                    FROM c2c_items_snapshot s
                                    JOIN c2c_items i ON i.c2c_items_id = s.c2c_items_id
                                    WHERE datetime(COALESCE(i.updated_at, i.created_at)) >= datetime(:cutoff)
                                    """
                                ),
                                {"cutoff": cutoff},
                            ).scalar()
                            or 0
                        )
                    else:
                        recent_rows = int(
                            conn.execute(
                                sa.text(
                                    """
                                    SELECT COUNT(*)
                                    FROM c2c_items_snapshot s
                                    JOIN c2c_items i ON i.c2c_items_id = s.c2c_items_id
                                    WHERE COALESCE(i.updated_at, i.created_at) >= :cutoff
                                    """
                                ),
                                {"cutoff": cutoff},
                            ).scalar()
                            or 0
                        )
                except Exception:
                    recent_rows = None
            for ts_col in ("updated_at", "recorded_at", "created_at"):
                if recent_rows is not None:
                    break
                if ts_col not in columns:
                    continue
                quoted_ts_col = identifier_preparer.quote(ts_col)
                try:
                    if dialect == "sqlite":
                        recent_rows = int(
                            conn.execute(
                                sa.text(
                                    f"SELECT COUNT(*) FROM {quoted_table} "
                                    f"WHERE {quoted_ts_col} IS NOT NULL AND datetime({quoted_ts_col}) >= datetime(:cutoff)"
                                ),
                                {"cutoff": cutoff},
                            ).scalar()
                            or 0
                        )
                    else:
                        recent_rows = int(
                            conn.execute(
                                sa.text(
                                    f"SELECT COUNT(*) FROM {quoted_table} "
                                    f"WHERE {quoted_ts_col} IS NOT NULL AND {quoted_ts_col} >= :cutoff"
                                ),
                                {"cutoff": cutoff},
                            ).scalar()
                            or 0
                        )
                except Exception:
                    recent_rows = None
                break

            table_bytes: Optional[int] = None
            index_bytes: Optional[int] = None
            total_relation_bytes: Optional[int] = None
            if dialect == "sqlite":
                if sqlite_dbstat_map:
                    try:
                        index_names = [str(idx.get("name") or "").strip() for idx in inspector.get_indexes(table_name)]
                    except Exception:
                        index_names = []
                    table_bytes = int(sqlite_dbstat_map.get(table_name, 0))
                    index_bytes = sum(int(sqlite_dbstat_map.get(index_name, 0)) for index_name in index_names if index_name)
                    total_relation_bytes = table_bytes + index_bytes
            elif dialect == "postgresql":
                schema = str(inspector.default_schema_name or "public")
                relation_name = f"{schema}.{table_name}"
                table_bytes = int(
                    conn.execute(sa.text("SELECT COALESCE(pg_table_size(to_regclass(:rel)), 0)"), {"rel": relation_name}).scalar() or 0
                )
                index_bytes = int(
                    conn.execute(sa.text("SELECT COALESCE(pg_indexes_size(to_regclass(:rel)), 0)"), {"rel": relation_name}).scalar() or 0
                )
                total_relation_bytes = table_bytes + index_bytes
            elif backend_name == "cloudflare" or dialect == "cloudflare_d1":
                # D1 does not expose per-table bytes directly; estimate by row payload and index key width.
                quoted_columns = [
                    identifier_preparer.quote(str(col.get("name") or ""))
                    for col in inspector.get_columns(table_name)
                    if str(col.get("name") or "").strip()
                ]
                avg_row_payload = 0.0
                if quoted_columns:
                    sum_expr = " + ".join(f"COALESCE(LENGTH(CAST({col_name} AS BLOB)), 0)" for col_name in quoted_columns)
                    try:
                        avg_row_payload = float(
                            conn.execute(
                                sa.text(f"SELECT COALESCE(AVG({sum_expr}), 0) FROM {quoted_table}")
                            ).scalar()
                            or 0.0
                        )
                    except Exception:
                        avg_row_payload = 0.0
                row_overhead = 24.0
                table_bytes = int(max(0.0, (avg_row_payload + row_overhead) * float(row_count)))

                idx_total = 0.0
                try:
                    idx_defs = inspector.get_indexes(table_name)
                except Exception:
                    idx_defs = []
                for idx_def in idx_defs:
                    col_names = [
                        identifier_preparer.quote(str(name))
                        for name in (idx_def.get("column_names") or [])
                        if str(name or "").strip()
                    ]
                    if not col_names:
                        continue
                    idx_expr = " + ".join(f"COALESCE(LENGTH(CAST({col_name} AS BLOB)), 0)" for col_name in col_names)
                    try:
                        avg_key_payload = float(
                            conn.execute(
                                sa.text(f"SELECT COALESCE(AVG({idx_expr}), 0) FROM {quoted_table}")
                            ).scalar()
                            or 0.0
                        )
                    except Exception:
                        avg_key_payload = 0.0
                    idx_entry_overhead = 16.0
                    idx_total += max(0.0, (avg_key_payload + idx_entry_overhead) * float(row_count))
                index_bytes = int(idx_total)
                total_relation_bytes = table_bytes + index_bytes

            table_rows.append(
                {
                    "name": table_name,
                    "row_count": row_count,
                    "recent_rows": recent_rows,
                    "table_bytes": table_bytes,
                    "index_bytes": index_bytes,
                    "total_bytes": total_relation_bytes,
                }
            )

    if dialect == "sqlite" and not sqlite_dbstat_map and sqlite_used_bytes is not None and table_rows:
        total_weight = sum(max(int(item.get("row_count") or 0), 1) for item in table_rows)
        if total_weight > 0:
            allocated = 0
            for idx, item in enumerate(table_rows):
                weight = max(int(item.get("row_count") or 0), 1)
                if idx == len(table_rows) - 1:
                    est_total = max(0, int(sqlite_used_bytes) - allocated)
                else:
                    est_total = max(0, int(sqlite_used_bytes * weight / total_weight))
                    allocated += est_total
                item["table_bytes"] = est_total
                item["index_bytes"] = 0
                item["total_bytes"] = est_total
            warnings.append("sqlite dbstat unavailable; table/index sizes are estimated by row count")
    if (backend_name == "cloudflare" or dialect == "cloudflare_d1") and table_rows:
        warnings.append("cloudflare d1 table/index sizes are estimated from row payload and index key width")

    table_rows.sort(
        key=lambda item: (
            int(item.get("total_bytes") or 0),
            int(item.get("row_count") or 0),
            str(item.get("name") or ""),
        ),
        reverse=True,
    )
    top_tables = table_rows[:top_n]
    total_relation_bytes = sum(int(item.get("total_bytes") or 0) for item in table_rows)
    total_rows = sum(int(item.get("row_count") or 0) for item in table_rows)
    recent_total_rows = sum(int(item.get("recent_rows") or 0) for item in table_rows if item.get("recent_rows") is not None)

    return {
        "generated_at": generated_at,
        "backend": get_db_backend_name(),
        "dialect": dialect,
        "days_window": days,
        "table_count": len(table_rows),
        "total_rows": total_rows,
        "recent_total_rows": recent_total_rows,
        "total_db_bytes": sqlite_total_bytes if dialect == "sqlite" else postgres_total_bytes,
        "used_db_bytes": sqlite_used_bytes if dialect == "sqlite" else None,
        "free_db_bytes": sqlite_free_bytes if dialect == "sqlite" else None,
        "wal_bytes": sqlite_wal_bytes if dialect == "sqlite" else None,
        "tables_total_bytes": total_relation_bytes,
        "skipped_tables": skipped_tables,
        "warnings": warnings,
        "tables": top_tables,
    }


def repair_orphan_market_data_batch(
    limit: int = 2000,
    progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    backend = _require_sqlalchemy_backend()
    engine = backend._engine
    dialect = str(engine.dialect.name or "").lower()
    batch_size = max(1, int(limit or 2000))

    with backend.session() as session:
        inspector = sa.inspect(engine)
        c2c_columns = {str(col.get("name") or "") for col in inspector.get_columns("c2c_items")}
        has_detail_json = "detail_json" in c2c_columns
        orphan_total_before_batch = int(
            session.execute(
                select(func.count(C2CItem.c2c_items_id)).where(
                    ~select(C2CItemSnapshot.id)
                    .join(Product, Product.id == C2CItemSnapshot.product_id)
                    .where(C2CItemSnapshot.c2c_items_id == C2CItem.c2c_items_id)
                    .exists()
                )
            ).scalar()
            or 0
        )
        candidate_rows = session.scalars(
            select(C2CItem)
            .where(
                ~select(C2CItemSnapshot.id)
                .join(Product, Product.id == C2CItemSnapshot.product_id)
                .where(C2CItemSnapshot.c2c_items_id == C2CItem.c2c_items_id)
                .exists()
            )
            .order_by(
                func.coalesce(C2CItem.created_at, C2CItem.updated_at).desc(),
                C2CItem.c2c_items_id.desc(),
            )
            .limit(batch_size)
        ).all()

        total_items = len(candidate_rows)
        created_product_count = 0
        created_snapshot_count = 0
        success_count = 0
        skipped_count = 0
        skipped_empty_detail = 0
        skipped_without_items_id = 0
        error_count = 0
        fallback_detail_json_used = 0
        error_samples: List[Dict[str, Any]] = []
        max_error_samples = 50

        def _add_error(c2c_items_id: int, reason: str) -> None:
            nonlocal error_count
            error_count += 1
            if len(error_samples) < max_error_samples:
                error_samples.append({"c2c_items_id": int(c2c_items_id), "reason": str(reason)})

        if progress_cb:
            progress_cb(
                {
                    "processed_items": 0,
                    "total_items": total_items,
                    "success_count": 0,
                    "skipped_count": 0,
                    "created_products": 0,
                    "created_snapshots": 0,
                }
            )

        for idx, row in enumerate(candidate_rows, start=1):
            try:
                detail_list, parse_reason = _decode_detail_blob_with_reason(row.detail_blob)
                if not detail_list and has_detail_json:
                    detail_json_value = session.execute(
                        sa.text("SELECT detail_json FROM c2c_items WHERE c2c_items_id = :cid"),
                        {"cid": int(row.c2c_items_id)},
                    ).scalar()
                    detail_list = _decode_detail_json_text(detail_json_value)
                    if detail_list:
                        fallback_detail_json_used += 1
                if not detail_list:
                    skipped_count += 1
                    skipped_empty_detail += 1
                    _add_error(
                        int(row.c2c_items_id),
                        f"empty_or_unparseable_detail_blob:{parse_reason or 'unknown'}",
                    )
                    if progress_cb:
                        progress_cb(
                            {
                                "processed_items": idx,
                                "total_items": total_items,
                                "success_count": success_count,
                                "skipped_count": skipped_count,
                                "created_products": created_product_count,
                                "created_snapshots": created_snapshot_count,
                            }
                        )
                    continue
                ts = str(row.created_at or row.updated_at or _now())
                total_market = 0
                for d_item in detail_list:
                    try:
                        total_market += int(d_item.get("marketPrice") or 0)
                    except Exception:
                        continue

                had_linked_product = False
                row_valid_detail_count = 0
                for d_item in detail_list:
                    items_id = (
                        d_item.get("itemsId")
                        if isinstance(d_item, dict)
                        else None
                    )
                    if items_id is None and isinstance(d_item, dict):
                        items_id = d_item.get("items_id")
                    if items_id is None and isinstance(d_item, dict):
                        items_id = d_item.get("itemId")
                    if items_id is None:
                        continue
                    try:
                        parsed_items_id = int(items_id)
                    except Exception:
                        continue
                    row_valid_detail_count += 1

                    try:
                        parsed_blindbox_id = int(d_item.get("blindBoxId")) if d_item.get("blindBoxId") is not None else 0
                    except Exception:
                        parsed_blindbox_id = 0
                    try:
                        parsed_sku_id = int(d_item.get("skuId")) if d_item.get("skuId") is not None else 0
                    except Exception:
                        parsed_sku_id = 0
                    try:
                        parsed_market_price = int(d_item.get("marketPrice") or 0)
                    except Exception:
                        parsed_market_price = 0

                    product = session.scalar(
                        select(Product).where(
                            Product.blindbox_id == parsed_blindbox_id,
                            Product.items_id == parsed_items_id,
                            Product.sku_id == parsed_sku_id,
                        )
                    )
                    if product is None:
                        product = Product(
                            blindbox_id=parsed_blindbox_id,
                            items_id=parsed_items_id,
                            sku_id=parsed_sku_id,
                            created_at=ts,
                            updated_at=ts,
                        )
                        session.add(product)
                        session.flush()
                        created_product_count += 1
                    product.name = d_item.get("name", product.name)
                    product.img_url = d_item.get("img") or d_item.get("imgUrl") or d_item.get("image") or product.img_url
                    product.market_price = parsed_market_price
                    product.updated_at = ts

                    est_price: Optional[int] = None
                    if row.price is not None and total_market > 0:
                        try:
                            est_price = int(float(row.price) * float(parsed_market_price) / float(total_market))
                        except Exception:
                            est_price = None

                    existing_snapshot = session.scalar(
                        select(C2CItemSnapshot.id).where(
                            C2CItemSnapshot.c2c_items_id == int(row.c2c_items_id),
                            C2CItemSnapshot.product_id == int(product.id),
                            C2CItemSnapshot.snapshot_at == ts,
                        )
                    )
                    if existing_snapshot is None:
                        session.add(
                            C2CItemSnapshot(
                                c2c_items_id=int(row.c2c_items_id),
                                snapshot_at=ts,
                                product_id=int(product.id),
                                est_price=est_price,
                            )
                        )
                        created_snapshot_count += 1
                    had_linked_product = True

                if had_linked_product:
                    session.execute(
                        sa.text(
                            """
                            DELETE FROM c2c_items_snapshot
                            WHERE c2c_items_id = :c2c_items_id
                              AND product_id NOT IN (SELECT id FROM product)
                            """
                        ),
                        {"c2c_items_id": int(row.c2c_items_id)},
                    )
                    success_count += 1
                else:
                    skipped_count += 1
                    if row_valid_detail_count == 0:
                        skipped_without_items_id += 1
                        _add_error(int(row.c2c_items_id), "detail_items_missing_items_id")
                    else:
                        _add_error(int(row.c2c_items_id), "detail_present_but_no_link_created")
            except Exception as exc:
                skipped_count += 1
                _add_error(int(row.c2c_items_id), f"exception:{exc.__class__.__name__}:{exc}")

            if progress_cb:
                progress_cb(
                    {
                        "processed_items": idx,
                        "total_items": total_items,
                        "success_count": success_count,
                        "skipped_count": skipped_count,
                        "created_products": created_product_count,
                        "created_snapshots": created_snapshot_count,
                    }
                )

        remaining_orphan_items = int(
            session.execute(
                sa.text(
                    """
                    SELECT COUNT(*)
                    FROM c2c_items i
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM c2c_items_snapshot s
                        JOIN product p ON p.id = s.product_id
                        WHERE s.c2c_items_id = i.c2c_items_id
                    )
                    """
                )
            ).scalar()
            or 0
        )
        remaining_orphan_snapshots = int(
            session.execute(
                sa.text(
                    """
                    SELECT COUNT(*)
                    FROM c2c_items_snapshot s
                    LEFT JOIN product p ON p.id = s.product_id
                    WHERE p.id IS NULL
                    """
                )
            ).scalar()
            or 0
        )

    return {
        "ok": True,
        "dialect": dialect,
        "batch_size": batch_size,
        "orphan_total_before_batch": orphan_total_before_batch,
        "scanned_orphan_items": total_items,
        "scanned_items": total_items,
        "success_count": success_count,
        "skipped_count": skipped_count,
        "created_products": created_product_count,
        "created_snapshots": created_snapshot_count,
        "skipped_empty_detail": skipped_empty_detail,
        "skipped_without_items_id": skipped_without_items_id,
        "fallback_detail_json_used": fallback_detail_json_used,
        "error_count": error_count,
        "error_samples": error_samples,
        "remaining_orphan_items": remaining_orphan_items,
        "remaining_orphan_snapshots": remaining_orphan_snapshots,
    }


def prune_orphan_old_market_data() -> Dict[str, Any]:
    return repair_orphan_market_data_batch(limit=2000)


def save_items(items: List[Dict[str, Any]]) -> Tuple[int, int]:
    backend = _require_sqlalchemy_backend()
    backend_name = get_db_backend_name()
    is_cloudflare = backend_name == "cloudflare"
    ids = [int(it["c2cItemsId"]) for it in items if it.get("c2cItemsId") is not None]
    inserted = 0
    saved = 0

    with backend.session() as session:
        existing_rows = {}
        if ids:
            rows = session.scalars(
                select(C2CItem).where(C2CItem.c2c_items_id.in_(ids))
            ).all()
            existing_rows = {int(row.c2c_items_id): row for row in rows}

        pending_detail_blob_updates: List[Tuple[int, str]] = []

        for it in items:
            item_id = it.get("c2cItemsId")
            if item_id is None:
                continue
            try:
                item_id = int(item_id)
            except Exception:
                continue

            try:
                new_price = it.get("price")
                timestamp = _now()
                row = existing_rows.get(item_id)
                is_new = row is None
                if row is None:
                    # Keep a minimal parent row so snapshot FK can be created in this transaction.
                    row = C2CItem(c2c_items_id=item_id)
                    session.add(row)
                    existing_rows[item_id] = row

                detail_list = it.get("detailDtoList", [])
                if not isinstance(detail_list, list):
                    detail_list = []
                existing_detail_list: List[Dict[str, Any]] = []
                if getattr(row, "detail_blob", None):
                    existing_detail_list = _decode_detail_blob(getattr(row, "detail_blob", None))
                materialized_detail_list: List[Dict[str, Any]] = []
                if "detailDtoList" in it:
                    if detail_list:
                        materialized_detail_list = _merge_detail_list_with_existing(detail_list, existing_detail_list)
                    else:
                        materialized_detail_list = existing_detail_list
                elif is_new:
                    materialized_detail_list = []
                else:
                    materialized_detail_list = existing_detail_list

                details_snapshot_at = _snapshot_now()
                total_market_price = 0
                for d_item in materialized_detail_list:
                    try:
                        total_market_price += int(d_item.get("marketPrice", 0) or 0)
                    except Exception:
                        continue

                # Write order: product -> snapshot -> c2c_items/blob.
                item_snapshot_models: List[C2CItemSnapshot] = []
                for d_item in materialized_detail_list:
                    d_items_id = d_item.get("itemsId")
                    if not d_items_id:
                        continue
                    try:
                        parsed_items_id = int(d_items_id)
                    except Exception:
                        continue
                    market_price = d_item.get("marketPrice", 0)
                    try:
                        parsed_market_price = int(market_price or 0)
                    except Exception:
                        parsed_market_price = 0
                    parsed_blindbox_id: Optional[int] = None
                    parsed_sku_id: Optional[int] = None
                    try:
                        raw_blindbox = d_item.get("blindBoxId")
                        if raw_blindbox is not None:
                            parsed_blindbox_id = int(raw_blindbox)
                    except Exception:
                        parsed_blindbox_id = None
                    try:
                        raw_sku = d_item.get("skuId")
                        if raw_sku is not None:
                            parsed_sku_id = int(raw_sku)
                    except Exception:
                        parsed_sku_id = None

                    est_price: Optional[int] = None
                    if new_price is not None and total_market_price > 0:
                        try:
                            est_price = int(float(new_price) * float(parsed_market_price) / float(total_market_price))
                        except Exception:
                            est_price = None
                    if parsed_blindbox_id is None:
                        parsed_blindbox_id = 0
                    if parsed_sku_id is None:
                        parsed_sku_id = 0
                    existing_product = session.scalar(
                        select(Product).where(
                            Product.blindbox_id == parsed_blindbox_id,
                            Product.items_id == parsed_items_id,
                            Product.sku_id == parsed_sku_id,
                        )
                    )
                    if existing_product is None:
                        existing_product = Product(
                            blindbox_id=parsed_blindbox_id,
                            items_id=parsed_items_id,
                            sku_id=parsed_sku_id,
                            created_at=timestamp,
                        )
                        session.add(existing_product)
                        session.flush()
                    existing_product.name = d_item.get("name", existing_product.name)
                    existing_product.img_url = _extract_img_from_detail_items([d_item])
                    existing_product.market_price = parsed_market_price
                    existing_product.updated_at = timestamp
                    item_snapshot_models.append(
                        C2CItemSnapshot(
                            c2c_items_id=item_id,
                            snapshot_at=details_snapshot_at,
                            product_id=int(existing_product.id),
                            est_price=est_price,
                        )
                    )
                if item_snapshot_models:
                    session.add_all(item_snapshot_models)
                    session.flush()

                category_id = _sanitize_str(it.get("categoryId"))
                if category_id is not None:
                    row.category_id = category_id
                row.type = it.get("type", row.type if row else None)
                row.c2c_items_name = it.get("c2cItemsName", row.c2c_items_name if row else None)
                row.total_items_count = it.get("totalItemsCount", row.total_items_count if row else None)
                row.price = new_price if new_price is not None else (row.price if row else None)
                row.show_price = it.get("showPrice", row.show_price if row else None)
                row.show_market_price = it.get("showMarketPrice", row.show_market_price if row else None)
                row.uid = it.get("uid", row.uid if row else None)
                row.payment_time = it.get("paymentTime", row.payment_time if row else None)
                if "isMyPublish" in it:
                    row.is_my_publish = 1 if it.get("isMyPublish") else 0
                incoming_uface = _normalize_uface(it.get("uface"))
                row.uface = incoming_uface or (row.uface if row else None)
                row.uname = it.get("uname", row.uname if row else None)
                row.publish_status = it.get("publishStatus")
                row.sale_status = it.get("saleStatus")
                row.drop_reason = _sanitize_str(it.get("dropReason"))
                if "detailDtoList" in it or is_new:
                    encoded_blob = _encode_detail_blob(materialized_detail_list)
                    if is_cloudflare:
                        pending_detail_blob_updates.append((item_id, encoded_blob.hex()))
                    else:
                        row.detail_blob = encoded_blob
                row.updated_at = timestamp
                if is_new:
                    row.created_at = timestamp

                saved += 1
                if is_new:
                    inserted += 1
            except Exception:
                continue

        if is_cloudflare and pending_detail_blob_updates:
            # D1 JSON transport may coerce bytes params to TEXT; use SQL BLOB literal.
            session.flush()
            for blob_item_id, blob_hex in pending_detail_blob_updates:
                session.execute(
                    sa.text(
                        f"""
                        UPDATE c2c_items
                        SET detail_blob = X'{blob_hex}'
                        WHERE c2c_items_id = :c2c_items_id
                        """
                    ),
                    {"c2c_items_id": int(blob_item_id)},
                )

    return saved, inserted


def filter_new_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return only items whose c2cItemsId does not already exist in the database."""
    backend = _require_sqlalchemy_backend()
    item_ids: List[int] = []
    for it in items:
        item_id = it.get("c2cItemsId")
        if item_id is None:
            continue
        try:
            item_ids.append(int(item_id))
        except Exception:
            continue
    if not item_ids:
        return []

    with backend.session() as session:
        existing_ids = set(
            int(row[0])
            for row in session.execute(
                select(C2CItem.c2c_items_id).where(C2CItem.c2c_items_id.in_(item_ids))
            ).all()
        )

    fresh_items: List[Dict[str, Any]] = []
    for it in items:
        item_id = it.get("c2cItemsId")
        if item_id is None:
            continue
        try:
            parsed_id = int(item_id)
        except Exception:
            continue
        if parsed_id not in existing_ids:
            fresh_items.append(it)
    return fresh_items


def update_item_status(
    c2c_items_id: int,
    publish_status: Optional[int],
    sale_status: Optional[int],
    drop_reason: Optional[str],
) -> bool:
    """Update only the status fields of a specific market item."""
    backend = _require_sqlalchemy_backend()
    with backend.session() as session:
        row = session.scalar(
            select(C2CItem).where(C2CItem.c2c_items_id == c2c_items_id)
        )
        if not row:
            return False
            
        row.publish_status = publish_status
        row.sale_status = sale_status
        row.drop_reason = _sanitize_str(drop_reason)
        row.updated_at = _now()  # Keep item "active" in 15-day filters
        session.commit()
    return True


def get_metadata(key: str, default: Optional[str] = None) -> Optional[str]:
    """Get a value from system_metadata table."""
    backend = _require_sqlalchemy_backend()
    with backend.session() as session:
        from bsm.orm_models import SystemMetadata
        val = session.scalar(
            select(SystemMetadata.value).where(SystemMetadata.key == key)
        )
        return val if val is not None else default


def set_metadata(key: str, value: Optional[str]) -> None:
    """Set a value in system_metadata table."""
    backend = _require_sqlalchemy_backend()
    with backend.session() as session:
        from bsm.orm_models import SystemMetadata
        row = session.scalar(
            select(SystemMetadata).where(SystemMetadata.key == key)
        )
        if not row:
            row = SystemMetadata(key=key, value=value)
            session.add(row)
        else:
            row.value = value
            row.updated_at = _now()
        session.commit()


def count_items() -> int:
    backend = _require_sqlalchemy_backend()
    with backend.session() as session:
        total = session.scalar(select(func.count()).select_from(C2CItem))
        return int(total or 0)


def search_items_by_pattern(pattern: str, limit: int = 50, page: int = 1) -> Tuple[List[Dict[str, Any]], int, int]:
    backend = _require_sqlalchemy_backend()
    with backend.session() as session:
        rows = session.scalars(
            select(C2CItem).order_by(C2CItem.updated_at.desc())
        ).all()
    regex = re.compile(pattern)
    matched: List[Dict[str, Any]] = []
    for row in rows:
        iid = row.c2c_items_id
        name = row.c2c_items_name
        price = row.show_price
        market = row.show_market_price
        if not regex.search(name or ""):
            continue
        matched.append(
            {
                "id": iid,
                "name": name,
                "price": price,
                "market": market,
                "url": (
                    "https://mall.bilibili.com/neul-next/index.html"
                    f"?page=magic-market_detail&noTitleBar=1&itemsId={iid}"
                ),
            }
        )
    total_count = len(matched)
    limit = max(1, limit)
    page = max(1, page)
    total_pages = (total_count + limit - 1) // limit if total_count > 0 else 0
    start = (page - 1) * limit
    end = start + limit
    return matched[start:end] if start < total_count else [], total_count, total_pages


def list_market_items(
    page: int = 1,
    limit: int = 20,
    sort_by: str = "TIME_DESC",
    time_filter_hours: int = 0,
    category_ids: Optional[Sequence[str]] = None,
) -> Tuple[List[Dict[str, Any]], int, int]:
    """Return paginated list of market items.
    
    sort_by: TIME_DESC, PRICE_ASC, PRICE_DESC
    time_filter_hours: 0 for all time, otherwise filter where updated_at >= N hours ago

    Returns (items, total_count, total_pages).
    """
    return _load_market_items_page(
        page=page,
        limit=limit,
        sort_by=sort_by,
        time_filter_hours=time_filter_hours,
        category_ids=category_ids,
    )


def search_market_items(
    keyword: str,
    page: int = 1,
    limit: int = 20,
    sort_by: str = "TIME_DESC",
    time_filter_hours: int = 0,
    category_ids: Optional[Sequence[str]] = None,
) -> Tuple[List[Dict[str, Any]], int, int]:
    """Search c2c_items by name keyword, paginated.

    Returns (items, total_count, total_pages).
    """
    kw = (keyword or "").strip()
    return _load_market_items_page(
        page=page,
        limit=limit,
        sort_by=sort_by,
        time_filter_hours=time_filter_hours,
        keyword=kw,
        category_ids=category_ids,
    )


def get_15d_listing_counts_batch(c2c_items_ids: List[int]) -> Dict[int, int]:
    """
    Given a list of c2c_items_ids, batch compute their 15-day listing counts.
    Returns a dict mapping c2c_items_id -> listing_count.
    """
    if not c2c_items_ids:
        return {}
    
    backend = _require_sqlalchemy_backend()
    cutoff = _utc_cutoff(days=15)
    current_details = _current_item_details_subquery("counts_current_details")
    with backend.session() as session:
        rows_items = (
            select(
                current_details.c.c2c_items_id,
                current_details.c.items_id,
                current_details.c.sku_id,
                func.row_number()
                .over(
                    partition_by=current_details.c.c2c_items_id,
                    order_by=current_details.c.id.asc(),
                )
                .label("row_num"),
            )
            .where(current_details.c.c2c_items_id.in_(c2c_items_ids))
            .subquery()
        )
        primary_rows = session.execute(
            select(rows_items.c.c2c_items_id, rows_items.c.items_id, rows_items.c.sku_id)
            .where(rows_items.c.row_num == 1)
        ).all()

        primary_key_map: Dict[int, Tuple[int, int]] = {}
        keys_to_query: set[Tuple[int, int]] = set()
        for c2c_id, items_id, sku_id in primary_rows:
            if items_id is None or sku_id is None:
                continue
            key = (int(items_id), int(sku_id))
            primary_key_map[int(c2c_id)] = key
            keys_to_query.add(key)

        if not keys_to_query:
            return {cid: 0 for cid in c2c_items_ids}

        rows_counts = session.execute(
            select(
                current_details.c.items_id,
                current_details.c.sku_id,
                func.count(func.distinct(current_details.c.c2c_items_id)),
            )
            .join(C2CItem, current_details.c.c2c_items_id == C2CItem.c2c_items_id)
            .where(
                sa.tuple_(current_details.c.items_id, current_details.c.sku_id).in_(keys_to_query)
            )
            .where(C2CItem.updated_at >= cutoff)
            .group_by(current_details.c.items_id, current_details.c.sku_id)
        ).all()

    counts_map = {
        (int(items_id), int(sku_id)): int(count)
        for items_id, sku_id, count in rows_counts
    }
    return {
        cid: counts_map.get(primary_key_map.get(cid, (0, 0)), 0)
        for cid in c2c_items_ids
    }


def get_item_price_history(c2c_items_id: int) -> List[Dict[str, Any]]:
    """Return item price points derived from detail snapshots, ordered by snapshot_at ASC."""
    backend = _require_sqlalchemy_backend()
    with backend.session() as session:
        rows = session.execute(
            select(
                C2CItemSnapshot.snapshot_at.label("recorded_at"),
                C2CItem.price.label("price"),
                C2CItem.show_price.label("show_price"),
            )
            .join(C2CItem, C2CItem.c2c_items_id == C2CItemSnapshot.c2c_items_id)
            .where(C2CItemSnapshot.c2c_items_id == c2c_items_id)
            .where(C2CItemSnapshot.snapshot_at.is_not(None))
            .group_by(
                C2CItemSnapshot.snapshot_at,
                C2CItem.price,
                C2CItem.show_price,
            )
            .order_by(C2CItemSnapshot.snapshot_at.asc())
        ).all()
    if not rows:
        with backend.session() as session:
            row = session.execute(
                select(
                    func.coalesce(C2CItem.created_at, C2CItem.updated_at).label("recorded_at"),
                    C2CItem.price.label("price"),
                    C2CItem.show_price.label("show_price"),
                ).where(C2CItem.c2c_items_id == c2c_items_id)
            ).first()
        if row is None or row.recorded_at is None:
            return []
        price_value = int(row.price) if row.price is not None else 0
        return [
            {
                "recorded_at": row.recorded_at,
                "price": price_value,
                "show_price": row.show_price or f"{price_value / 100:.2f}",
            }
        ]
    history: List[Dict[str, Any]] = []
    for row in rows:
        if row.recorded_at is None:
            continue
        price_value = int(row.price) if row.price is not None else 0
        history.append(
            {
                "recorded_at": row.recorded_at,
                "price": price_value,
                "show_price": row.show_price or f"{price_value / 100:.2f}",
            }
        )
    return history


def get_primary_product_key(c2c_items_id: int) -> Optional[Tuple[int, int]]:
    """Get the first (items_id, sku_id) associated with a c2c_items_id."""
    backend = _require_sqlalchemy_backend()
    with backend.session() as session:
        row = session.execute(
            select(Product.items_id, Product.sku_id)
            .join(C2CItemSnapshot, C2CItemSnapshot.product_id == Product.id)
            .where(C2CItemSnapshot.c2c_items_id == c2c_items_id)
            .order_by(C2CItemSnapshot.id.asc())
            .limit(1)
        ).first()
        if row is None or row[0] is None or row[1] is None:
            return None
        return int(row[0]), int(row[1])


def get_primary_items_id(c2c_items_id: int) -> Optional[int]:
    """Get the first official itemsId associated with a c2c_items_id."""
    primary = get_primary_product_key(c2c_items_id)
    return int(primary[0]) if primary is not None else None


def get_product_metadata(items_id: int) -> Optional[Dict[str, Any]]:
    """Get aggregated metadata for a specific official itemsId (Product)."""
    backend = _require_sqlalchemy_backend()
    cutoff = _utc_cutoff(days=15)
    current_details = _current_item_details_subquery("product_metadata_current_details")
    
    name_sq = (
        select(current_details.c.name)
        .where(current_details.c.items_id == items_id)
        .limit(1)
        .scalar_subquery()
    )
    img_url_sq = (
        select(current_details.c.img_url)
        .where(current_details.c.items_id == items_id)
        .limit(1)
        .scalar_subquery()
    )
    sku_id_sq = (
        select(current_details.c.sku_id)
        .where(current_details.c.items_id == items_id)
        .where(current_details.c.sku_id.is_not(None))
        .where(current_details.c.sku_id > 0)
        .order_by(current_details.c.id.asc())
        .limit(1)
        .scalar_subquery()
    )
    stats_sq = (
        select(
            func.min(current_details.c.est_price).label("price_min"),
            func.max(current_details.c.est_price).label("price_max"),
            func.count(func.distinct(C2CItem.c2c_items_id)).label("recent_listed_count"),
        )
        .join(current_details, C2CItem.c2c_items_id == current_details.c.c2c_items_id)
        .where(current_details.c.items_id == items_id)
        .where(C2CItem.updated_at >= cutoff)
        .subquery()
    )

    with backend.session() as session:
        row = session.execute(
            select(
                name_sq.label("name"),
                img_url_sq.label("img_url"),
                sku_id_sq.label("sku_id"),
                stats_sq.c.price_min,
                stats_sq.c.price_max,
                stats_sq.c.recent_listed_count,
            )
        ).first()

    if row is None or row.name is None:
        return None

    price_min = int(row.price_min) if row.price_min is not None else None
    price_max = int(row.price_max) if row.price_max is not None else None
    sku_id = int(row.sku_id) if row.sku_id is not None else None
    recent_listed_count = int(row.recent_listed_count) if row.recent_listed_count is not None else 0

    return {
        "items_id": items_id,
        "sku_id": sku_id,
        "name": row.name,
        "img_url": row.img_url,
        "price_min": price_min,
        "price_max": price_max,
        "recent_listed_count": recent_listed_count,
        "show_price_min": f"{price_min / 100:.2f}" if price_min is not None else None,
        "show_price_max": f"{price_max / 100:.2f}" if price_max is not None else None,
    }


def get_product_price_history(items_id: int, sku_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Return product-level history from detail snapshots in the last 15 days."""
    backend = _require_sqlalchemy_backend()
    cutoff = _utc_cutoff(days=15)
    with backend.session() as session:
        stmt = (
            select(
                C2CItemSnapshot.snapshot_at.label("recorded_at"),
                func.min(C2CItemSnapshot.est_price).label("est_price"),
                C2CItem.c2c_items_name,
                C2CItem.c2c_items_id,
            )
            .join(C2CItem, C2CItem.c2c_items_id == C2CItemSnapshot.c2c_items_id)
            .join(Product, Product.id == C2CItemSnapshot.product_id)
            .where(Product.items_id == items_id)
            .where(C2CItemSnapshot.snapshot_at >= cutoff)
            .group_by(
                C2CItemSnapshot.snapshot_at,
                C2CItem.c2c_items_name,
                C2CItem.c2c_items_id,
            )
            .order_by(C2CItemSnapshot.snapshot_at.asc())
        )
        if sku_id is not None:
            stmt = stmt.where(Product.sku_id == sku_id)
        rows = session.execute(stmt).all()
    history = []
    for row in rows:
        history.append({
            "recorded_at": row[0],
            "price": int(row[1]) if row[1] is not None else 0,
            "show_price": f"{int(row[1] or 0) / 100:.2f}",
            "name": row[2],
            "c2c_items_id": row[3],
        })
    return history


def get_sku_price_history(sku_id: int) -> List[Dict[str, Any]]:
    """Return SKU-level history from detail snapshots in the last 15 days."""
    backend = _require_sqlalchemy_backend()
    cutoff = _utc_cutoff(days=15)
    with backend.session() as session:
        rows = session.execute(
            select(
                C2CItemSnapshot.snapshot_at.label("recorded_at"),
                func.min(C2CItemSnapshot.est_price).label("est_price"),
                C2CItem.c2c_items_name,
                C2CItem.c2c_items_id,
            )
            .join(C2CItem, C2CItem.c2c_items_id == C2CItemSnapshot.c2c_items_id)
            .join(Product, Product.id == C2CItemSnapshot.product_id)
            .where(Product.sku_id == sku_id)
            .where(C2CItemSnapshot.snapshot_at >= cutoff)
            .group_by(
                C2CItemSnapshot.snapshot_at,
                C2CItem.c2c_items_name,
                C2CItem.c2c_items_id,
            )
            .order_by(C2CItemSnapshot.snapshot_at.asc())
        ).all()
    history: List[Dict[str, Any]] = []
    for row in rows:
        history.append(
            {
                "recorded_at": row[0],
                "price": int(row[1]) if row[1] is not None else 0,
                "show_price": f"{int(row[1] or 0) / 100:.2f}",
                "name": row[2],
                "c2c_items_id": row[3],
            }
        )
    return history


def get_recent_15d_listings(items_id: int, page: int = 1, limit: int = 20, sort_by: str = "TIME_DESC") -> Tuple[List[Dict[str, Any]], int, int]:
    """Return specific listing details for the last 15 days containing this items_id, paginated."""
    _, listings, total_count, total_pages = _load_recent_15d_listings_page(
        items_id_expr=items_id,
        page=page,
        limit=limit,
        sort_by=sort_by,
    )
    return listings, total_count, total_pages


def get_market_item_recent_15d_listings(
    c2c_items_id: int,
    page: int = 1,
    limit: int = 20,
    sort_by: str = "TIME_DESC",
) -> Tuple[Optional[int], List[Dict[str, Any]], int, int]:
    current_details = _current_item_details_subquery("market_item_recent_current_details")
    items_id_sq = (
        select(current_details.c.items_id)
        .where(current_details.c.c2c_items_id == c2c_items_id)
        .order_by(current_details.c.id.asc())
        .limit(1)
        .scalar_subquery()
    )
    sku_id_sq = (
        select(current_details.c.sku_id)
        .where(current_details.c.c2c_items_id == c2c_items_id)
        .order_by(current_details.c.id.asc())
        .limit(1)
        .scalar_subquery()
    )
    return _load_recent_15d_listings_page(
        items_id_expr=items_id_sq,
        sku_id_expr=sku_id_sq,
        page=page,
        limit=limit,
        sort_by=sort_by,
    )

def get_market_item(c2c_items_id: int) -> Optional[Dict[str, Any]]:
    """Return a single market item by ID."""
    backend = _require_sqlalchemy_backend()
    recent_count_sq = _market_recent_listing_count_expr()
    with backend.session() as session:
        row = session.execute(
            select(
                C2CItem,
                func.coalesce(recent_count_sq, 0).label("recent_listed_count"),
            ).where(C2CItem.c2c_items_id == c2c_items_id)
        ).first()
    if row is None or row[0] is None:
        return None
    details_map = _load_current_details_for_c2c_ids([int(c2c_items_id)])
    return _market_item_to_dict(
        row[0],
        int(row.recent_listed_count or 0),
        details_map.get(int(c2c_items_id), []),
    )


def is_item_detail_blob_empty(c2c_items_id: int) -> bool:
    backend = _require_sqlalchemy_backend()
    with backend.session() as session:
        row = session.scalar(
            select(C2CItem).where(C2CItem.c2c_items_id == c2c_items_id)
        )
    if row is None:
        return True
    detail_list = _decode_detail_blob(getattr(row, "detail_blob", None))
    return len(detail_list) == 0

def get_15d_listing_count(items_id: int) -> int:
    """Return the number of distinct c2c listings containing the official items_id in the last 15 days."""
    if not items_id:
        return 0
    backend = _require_sqlalchemy_backend()
    current_details = _current_item_details_subquery("single_count_current_details")
    with backend.session() as session:
        total = session.scalar(
            select(func.count(func.distinct(current_details.c.c2c_items_id)))
            .join(C2CItem, current_details.c.c2c_items_id == C2CItem.c2c_items_id)
            .where(current_details.c.items_id == items_id)
            .where(C2CItem.updated_at >= _utc_cutoff(days=15))
        )
        return int(total or 0)


def save_bili_session(
    cookies: str,
    login_username: str,
    created_by: str = "",
    status: str = "active",
) -> None:
    login_username = str(login_username or "").strip()
    created_by_value = str(created_by or "").strip() or None
    if not login_username:
        raise ValueError("login_username is required")
    backend = _require_sqlalchemy_backend()
    timestamp = _now()
    with backend.session() as session:
        row = session.scalar(
            select(BiliSession).where(BiliSession.login_username == login_username)
        )
        if row is None:
            row = BiliSession(
                login_username=login_username,
                fetch_count=0,
            )
            session.add(row)
        row.cookies = cookies
        row.created_by = created_by_value
        row.status = status
        row.login_at = timestamp
        row.last_checked_at = timestamp
        row.last_error = None
        row.updated_at = timestamp


def list_bili_sessions(status: Optional[str] = "active") -> List[Dict[str, Any]]:
    backend = _require_sqlalchemy_backend()
    with backend.session() as session:
        stmt = select(BiliSession)
        if status:
            stmt = stmt.where(BiliSession.status == status)
        stmt = stmt.order_by(
            func.coalesce(BiliSession.last_used_at, BiliSession.created_at).asc(),
            BiliSession.id.asc(),
        )
        rows = session.scalars(stmt).all()
        return [_bili_session_to_dict(row) for row in rows]


def load_next_bili_session() -> Dict[str, Any]:
    backend = _require_sqlalchemy_backend()
    runtime = _load_bili_session_runtime_settings()
    mode = runtime["mode"]
    cooldown_seconds = runtime["cooldown_seconds"]
    with backend.session() as session:
        stmt = (
            select(BiliSession)
            .where(
                and_(
                    BiliSession.status == "active",
                    _available_bili_session_condition(cooldown_seconds),
                )
            )
        )
        if mode == "random":
            stmt = stmt.order_by(func.random())
        else:
            stmt = stmt.order_by(
                func.coalesce(BiliSession.last_used_at, BiliSession.created_at).asc(),
                BiliSession.id.asc(),
            )
        row = session.scalar(stmt)
        if row is None:
            return {}
        payload = _bili_session_to_dict(row)
        timestamp = _now()
        row.last_used_at = timestamp
        row.updated_at = timestamp
        return payload


def clear_bili_sessions(login_username: Optional[str] = None) -> None:
    backend = _require_sqlalchemy_backend()
    with backend.session() as session:
        stmt = delete(BiliSession)
        if login_username:
            stmt = stmt.where(BiliSession.login_username == login_username)
        session.execute(stmt)


def has_active_bili_session() -> bool:
    backend = _require_sqlalchemy_backend()
    cooldown_seconds = _load_bili_session_runtime_settings()["cooldown_seconds"]
    with backend.session() as session:
        return bool(
            session.scalar(
                select(BiliSession.id)
                .where(
                    and_(
                        BiliSession.status == "active",
                        _available_bili_session_condition(cooldown_seconds),
                    )
                )
                .limit(1)
            )
        )


def mark_bili_session_result(login_username: str, error: Optional[str] = None) -> None:
    backend = _require_sqlalchemy_backend()
    with backend.session() as session:
        row = session.scalar(
            select(BiliSession).where(BiliSession.login_username == login_username)
        )
        if row is None:
            return
        timestamp = _now()
        row.last_checked_at = timestamp
        row.last_error = error
        row.updated_at = timestamp


def record_bili_session_fetch_success(login_username: str, fetched_count: int = 0) -> None:
    increment = max(0, int(fetched_count))
    backend = _require_sqlalchemy_backend()
    with backend.session() as session:
        row = session.scalar(
            select(BiliSession).where(BiliSession.login_username == login_username)
        )
        if row is None:
            return
        timestamp = _now()
        row.fetch_count = int(row.fetch_count or 0) + increment
        row.last_success_fetch_at = timestamp
        row.last_checked_at = timestamp
        row.last_error = None
        row.updated_at = timestamp


def delete_bili_session(login_username: str) -> None:
    backend = _require_sqlalchemy_backend()
    with backend.session() as session:
        session.execute(
            delete(BiliSession).where(BiliSession.login_username == login_username)
        )


def list_access_users(status: Optional[str] = None) -> List[Dict[str, Any]]:
    backend = _require_sqlalchemy_backend()
    with backend.session() as session:
        stmt = select(AccessUser)
        if status:
            stmt = stmt.where(AccessUser.status == status)
        stmt = stmt.order_by(
            AccessUser.created_at.desc(),
            AccessUser.id.desc(),
            AccessUser.username.desc(),
        )
        rows = session.scalars(stmt).all()
        return [_access_user_to_dict(row) for row in rows]


def get_access_user(username: str) -> Optional[Dict[str, Any]]:
    username = str(username or "").strip()
    if not username:
        return None
    backend = _require_sqlalchemy_backend()
    with backend.session() as session:
        row = session.scalar(select(AccessUser).where(AccessUser.username == username))
        return _access_user_to_dict(row) if row is not None else None


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
    username = str(username or "").strip()
    if not username:
        raise ValueError("username is required")
    backend = _require_sqlalchemy_backend()
    telegram_id_list = _json_list(list(telegram_ids or []))
    keyword_list = _json_list(list(keywords or []))
    role_list = _json_list(list(roles or []))
    with backend.session() as session:
        row = session.scalar(select(AccessUser).where(AccessUser.username == username))
        if row is None:
            row = AccessUser(username=username)
            session.add(row)
        row.display_name = str(display_name or "").strip()
        next_password = str(password_hash or "")
        if next_password and not is_password_hash(next_password):
            next_password = hash_password(next_password)
        row.password_hash = next_password
        row.telegram_ids_json = json.dumps(telegram_id_list, ensure_ascii=False)
        row.keywords_json = json.dumps(keyword_list, ensure_ascii=False)
        row.roles_json = json.dumps(role_list, ensure_ascii=False)
        row.notify_enabled = 1 if notify_enabled else 0
        row.status = str(status or "active")
        row.updated_at = _now()


def delete_access_user(username: str) -> None:
    username = str(username or "").strip()
    if not username:
        return
    backend = _require_sqlalchemy_backend()
    with backend.session() as session:
        session.execute(delete(AccessUser).where(AccessUser.username == username))
