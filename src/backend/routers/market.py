"""
Market router.

Routes:
  GET /api/market/items?page=1&limit=20
  GET /api/market/items/search?q=洛琪希&page=1&limit=20
  GET /api/market/items/{id}
  GET /api/product/{items_id}/{sku_id}/price-history
"""
from __future__ import annotations

from fastapi import APIRouter, Query, Depends, BackgroundTasks
from fastapi.responses import JSONResponse

import asyncio
import sys
from pathlib import Path

_SRC_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _SRC_ROOT not in sys.path:
    sys.path.insert(0, _SRC_ROOT)

from backend.auth import get_current_user  # noqa: E402
from bsm.db import (  # noqa: E402
    get_market_item,
    get_market_item_recent_15d_listings,
    get_primary_items_id,
    get_product_price_history,
    get_product_metadata,
    get_recent_15d_listings,
    list_market_items,
    search_market_items,
    save_items,
    load_next_bili_session,
    is_item_detail_blob_empty,
    update_item_status,
)
from bsm.mall import get_item_detail

router = APIRouter(dependencies=[Depends(get_current_user)])


def _hydrate_item_detail_task(item_id: int) -> None:
    """Best-effort background task: fetch detail and persist product/snapshot mapping."""
    sess = load_next_bili_session()
    if not sess or not sess.get("cookies"):
        return
    result = get_item_detail(str(sess.get("cookies") or ""), int(item_id))
    if not result or result.get("code") != 0:
        return
    payload = result.get("data")
    if not isinstance(payload, dict):
        return
    if payload.get("c2cItemsId") is None:
        payload = dict(payload)
        payload["c2cItemsId"] = int(item_id)
    try:
        save_items([payload])
    except Exception:
        return


@router.get("/api/market/items")
def api_list_market_items(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    sort_by: str = Query("TIME_DESC"),
    time_filter: int = Query(0, ge=0),
    category: str = Query(""),
) -> JSONResponse:
    category_ids = [item.strip() for item in category.split(",") if item.strip()]
    items, total_count, total_pages = list_market_items(
        page=page, limit=limit, sort_by=sort_by, time_filter_hours=time_filter, category_ids=category_ids
    )
    return JSONResponse(
        {
            "items": items,
            "pagination": {
                "page": page,
                "limit": limit,
                "total_count": total_count,
                "total_pages": total_pages,
            },
        }
    )


@router.get("/api/market/items/search")
def api_search_market_items(
    q: str = Query(""),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    sort_by: str = Query("TIME_DESC"),
    time_filter: int = Query(0, ge=0),
    category: str = Query(""),
) -> JSONResponse:
    category_ids = [item.strip() for item in category.split(",") if item.strip()]
    items, total_count, total_pages = search_market_items(
        keyword=q, page=page, limit=limit, sort_by=sort_by, time_filter_hours=time_filter, category_ids=category_ids
    )
    return JSONResponse(
        {
            "items": items,
            "query": q,
            "pagination": {
                "page": page,
                "limit": limit,
                "total_count": total_count,
                "total_pages": total_pages,
            },
        }
    )


@router.get("/api/product/{items_id}/{sku_id}/price-history")
def api_product_price_history(items_id: int, sku_id: int) -> JSONResponse:
    history = get_product_price_history(items_id, sku_id=sku_id)
    return JSONResponse({"items_id": items_id, "sku_id": sku_id, "history": history})


@router.get("/api/market/items/{item_id}/recent-listings")
def api_item_recent_listings(
    background_tasks: BackgroundTasks,
    item_id: int, 
    page: int = Query(1, ge=1), 
    limit: int = Query(20, ge=1, le=100),
    sort_by: str = Query("TIME_DESC")
) -> JSONResponse:
    scheduled_hydration = False
    if is_item_detail_blob_empty(item_id):
        background_tasks.add_task(_hydrate_item_detail_task, int(item_id))
        scheduled_hydration = True
    items_id, listings, total_count, total_pages = get_market_item_recent_15d_listings(
        item_id,
        page=page,
        limit=limit,
        sort_by=sort_by,
    )
    if not items_id:
        if not scheduled_hydration:
            background_tasks.add_task(_hydrate_item_detail_task, int(item_id))
    if not items_id:
        return JSONResponse({
            "item_id": item_id, 
            "items_id": None, 
            "listings": [],
            "total_count": 0,
            "total_pages": 0
        })
    return JSONResponse({
        "item_id": item_id, 
        "items_id": items_id, 
        "listings": listings,
        "total_count": total_count,
        "total_pages": total_pages
    })


@router.get("/api/market/items/{item_id}")
def api_get_market_item(item_id: int, background_tasks: BackgroundTasks) -> JSONResponse:
    if is_item_detail_blob_empty(item_id):
        background_tasks.add_task(_hydrate_item_detail_task, int(item_id))
    item = get_market_item(item_id)
    if item is not None and not item.get("img_url"):
        background_tasks.add_task(_hydrate_item_detail_task, int(item_id))
    if item is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"item": item})


@router.get("/api/market/product/{items_id}")
def api_get_product_metadata(items_id: int) -> JSONResponse:
    metadata = get_product_metadata(items_id)
    if metadata is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"product": metadata})


@router.get("/api/market/product/{items_id}/recent-listings")
def api_product_recent_listings(
    items_id: int, 
    page: int = Query(1, ge=1), 
    limit: int = Query(20, ge=1, le=100),
    sort_by: str = Query("TIME_DESC")
) -> JSONResponse:
    listings, total_count, total_pages = get_recent_15d_listings(items_id, page=page, limit=limit, sort_by=sort_by)
    return JSONResponse({
        "items_id": items_id, 
        "listings": listings,
        "total_count": total_count,
        "total_pages": total_pages
    })

@router.post("/api/market/items/batch-refresh")
async def api_batch_refresh(body: dict) -> JSONResponse:
    """Refresh status for a batch of item IDs (max 10). Returns results per item."""
    ids = body.get("ids", [])
    if not ids or not isinstance(ids, list):
        return JSONResponse({"error": "ids list required"}, status_code=400)
    ids = [int(i) for i in ids[:10]]  # cap at 10

    sess = load_next_bili_session()
    if not sess or not sess.get("cookies"):
        return JSONResponse({"error": "No active Bilibili session found"}, status_code=401)

    cookies = sess["cookies"]

    async def _refresh_one(c2c_id: int) -> dict:
        result = await asyncio.to_thread(get_item_detail, cookies, c2c_id)
        if result and result.get("code") == 0 and result.get("data"):
            d = result["data"]
            await asyncio.to_thread(
                update_item_status,
                c2c_items_id=c2c_id,
                publish_status=d.get("publishStatus"),
                sale_status=d.get("saleStatus"),
                drop_reason=d.get("dropReason"),
            )
            return {
                "c2c_items_id": c2c_id,
                "publish_status": d.get("publishStatus"),
                "sale_status": d.get("saleStatus"),
                "drop_reason": d.get("dropReason"),
                "ok": True,
            }
        return {"c2c_items_id": c2c_id, "ok": False}

    tasks = [_refresh_one(cid) for cid in ids]
    results = await asyncio.gather(*tasks)
    return JSONResponse({"results": list(results)})


@router.post("/api/market/items/{item_id}/refresh")
async def api_refresh_market_item(item_id: int) -> JSONResponse:
    sess = load_next_bili_session()
    if not sess or not sess.get("cookies"):
        return JSONResponse({"error": "No active Bilibili session found"}, status_code=401)
    
    cookies = sess["cookies"]
    result = get_item_detail(cookies, item_id)
    
    if not result or result.get("code") != 0:
        msg = result.get("message") if result else "Unknown error fetch detail"
        return JSONResponse({"error": msg}, status_code=500)
    
    item_data = result.get("data")
    if not item_data:
        return JSONResponse({"error": "Empty item data from Bilibili"}, status_code=500)
        
    update_item_status(
        c2c_items_id=item_id,
        publish_status=item_data.get("publishStatus"),
        sale_status=item_data.get("saleStatus"),
        drop_reason=item_data.get("dropReason")
    )
    
    # Reload item to return the updated record
    item = get_market_item(item_id)
    if item is None:
        return JSONResponse({"error": "Item not found in database"}, status_code=404)
        
        
    return JSONResponse({"item": item})

@router.post("/api/market/items/{item_id}/recent-listings/refresh")
async def api_refresh_item_recent_listings(
    item_id: int, 
    page: int = Query(1, ge=1), 
    limit: int = Query(20, ge=1, le=100),
    sort_by: str = Query("TIME_DESC")
) -> JSONResponse:
    sess = load_next_bili_session()
    if not sess or not sess.get("cookies"):
        return JSONResponse({"error": "No active Bilibili session found"}, status_code=401)
        
    cookies = sess["cookies"]
    items_id = get_primary_items_id(item_id)
    if not items_id:
        return JSONResponse({"error": "Item has no primary items_id"}, status_code=400)
        
    listings, total_count, total_pages = get_recent_15d_listings(items_id, page=page, limit=limit, sort_by=sort_by)
    
    refreshed_count = await _parallel_refresh_listings(cookies, listings)
            
    # Refetch the updated listings
    updated_listings, _, _ = get_recent_15d_listings(items_id, page=page, limit=limit, sort_by=sort_by)
            
    return JSONResponse({
        "items_id": items_id, 
        "listings": updated_listings,
        "total_count": total_count,
        "total_pages": total_pages,
        "refreshed_count": refreshed_count
    })

@router.post("/api/market/product/{items_id}/recent-listings/refresh")
async def api_refresh_product_recent_listings(
    items_id: int, 
    page: int = Query(1, ge=1), 
    limit: int = Query(20, ge=1, le=100),
    sort_by: str = Query("TIME_DESC")
) -> JSONResponse:
    sess = load_next_bili_session()
    if not sess or not sess.get("cookies"):
        return JSONResponse({"error": "No active Bilibili session found"}, status_code=401)
        
    cookies = sess["cookies"]
    listings, total_count, total_pages = get_recent_15d_listings(items_id, page=page, limit=limit, sort_by=sort_by)
    
    refreshed_count = await _parallel_refresh_listings(cookies, listings)
            
    # Refetch the updated listings
    updated_listings, _, _ = get_recent_15d_listings(items_id, page=page, limit=limit, sort_by=sort_by)
            
    return JSONResponse({
        "items_id": items_id, 
        "listings": updated_listings,
        "total_count": total_count,
        "total_pages": total_pages,
        "refreshed_count": refreshed_count
    })


async def _parallel_refresh_listings(cookies: str, listings: list) -> int:
    """Refresh status for a list of listings, 5 at a time in parallel."""
    sem = asyncio.Semaphore(5)
    refreshed_count = 0
    lock = asyncio.Lock()

    async def _refresh_one(c2c_id: int) -> None:
        nonlocal refreshed_count
        async with sem:
            result = await asyncio.to_thread(get_item_detail, cookies, c2c_id)
            if result and result.get("code") == 0 and result.get("data"):
                item_data = result.get("data")
                await asyncio.to_thread(
                    update_item_status,
                    c2c_items_id=c2c_id,
                    publish_status=item_data.get("publishStatus"),
                    sale_status=item_data.get("saleStatus"),
                    drop_reason=item_data.get("dropReason"),
                )
                async with lock:
                    refreshed_count += 1

    tasks = [_refresh_one(listing["c2c_items_id"]) for listing in listings]
    await asyncio.gather(*tasks)
    return refreshed_count
