from typing import Any, Dict, List, Tuple, Optional

from .mall import list_items, list_items_async


class ScanRateLimitedError(RuntimeError):
    pass


SCAN_REQUEST_TIMEOUT_SECONDS = 15
DEFAULT_PRICE_FILTERS = ["3000-5000", "5000-10000", "20000-0", "10000-20000"]
DEFAULT_DISCOUNT_FILTERS = ["70-100", "50-70", "30-50", "0-30"]


def scan_once(cookies: str, cfg: Dict[str, Any], next_id: Optional[str] = None) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    # Read filters from config, fallback to empty list or defaults if needed
    # (Though we usually want specific buckets to bypass waterfall limits)
    pf = cfg.get("price_filters")
    if pf is None:
        pf = list(DEFAULT_PRICE_FILTERS)
        
    df = cfg.get("discount_filters")
    if df is None:
        df = list(DEFAULT_DISCOUNT_FILTERS)
    
    categories = [c.strip() for c in (cfg.get("category") or "").split(",") if c.strip()]
    if not categories:
        categories = [None]
        
    all_items = []
    last_next_id = None
    
    for cat in categories:
        result = list_items(
            cookies,
            pf,
            df,
            cfg.get("sort_type", "TIME_DESC"),
            next_id,
            cat,
            timeout=float(cfg.get("scan_timeout_seconds") or SCAN_REQUEST_TIMEOUT_SECONDS),
        )
        if result.get("code") == 429:
            raise ScanRateLimitedError("B站返回 429，扫描频率过高")
            
        payload = result.get("data") or {}
        items = payload.get("data") or []
        if isinstance(items, list):
            if cat is not None:
                for item in items:
                    if isinstance(item, dict):
                        item["categoryId"] = cat
            all_items.extend(items)
        last_next_id = payload.get("nextId")
        
    return last_next_id, all_items


async def scan_once_async(cookies: str, cfg: Dict[str, Any], next_id: Optional[str] = None) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    pf = cfg.get("price_filters")
    if pf is None:
        pf = list(DEFAULT_PRICE_FILTERS)

    df = cfg.get("discount_filters")
    if df is None:
        df = list(DEFAULT_DISCOUNT_FILTERS)

    categories = [c.strip() for c in (cfg.get("category") or "").split(",") if c.strip()]
    if not categories:
        categories = [None]

    all_items = []
    last_next_id = None
    timeout = float(cfg.get("scan_timeout_seconds") or SCAN_REQUEST_TIMEOUT_SECONDS)

    for cat in categories:
        result = await list_items_async(
            cookies,
            pf,
            df,
            cfg.get("sort_type", "TIME_DESC"),
            next_id,
            cat,
            timeout=timeout,
        )
        if result.get("code") == 429:
            raise ScanRateLimitedError("B站返回 429，扫描频率过高")

        payload = result.get("data") or {}
        items = payload.get("data") or []
        if isinstance(items, list):
            if cat is not None:
                for item in items:
                    if isinstance(item, dict):
                        item["categoryId"] = cat
            all_items.extend(items)
        last_next_id = payload.get("nextId")

    return last_next_id, all_items
