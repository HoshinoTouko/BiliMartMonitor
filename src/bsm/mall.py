from typing import Any

import httpx
import requests

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0"


def list_items(
    cookies: str,
    price_filters,
    discount_filters,
    sort_type: str,
    next_id=None,
    category: str | None = None,
    timeout: float = 10,
) -> dict[str, Any]:
    url = "https://mall.bilibili.com/mall-magic-c/internet/c2c/v2/list"
    data = {
        "sortType": sort_type,
        "nextId": next_id,
        "priceFilters": price_filters or [],
        "discountFilters": discount_filters or [],
    }
    if category:
        data["categoryFilter"] = category
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "User-Agent": USER_AGENT,
        "Cookie": cookies,
        "Origin": "https://mall.bilibili.com",
        "Referer": "https://mall.bilibili.com/neul-next/index.html"
    }
    try:
        resp = requests.post(url, json=data, headers=headers, timeout=timeout)
    except Exception as e:
        return {"code": -1, "message": str(e), "data": {"data": [], "nextId": None}}
    try:
        return resp.json()
    except Exception:
        text = resp.text if hasattr(resp, "text") else ""
        return {"code": resp.status_code, "message": text[:200], "data": {"data": [], "nextId": None}}


async def list_items_async(
    cookies: str,
    price_filters,
    discount_filters,
    sort_type: str,
    next_id=None,
    category: str | None = None,
    timeout: float = 10,
) -> dict[str, Any]:
    url = "https://mall.bilibili.com/mall-magic-c/internet/c2c/v2/list"
    data = {
        "sortType": sort_type,
        "nextId": next_id,
        "priceFilters": price_filters or [],
        "discountFilters": discount_filters or [],
    }
    if category:
        data["categoryFilter"] = category
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "User-Agent": USER_AGENT,
        "Cookie": cookies,
        "Origin": "https://mall.bilibili.com",
        "Referer": "https://mall.bilibili.com/neul-next/index.html",
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=data, headers=headers)
    except Exception as e:
        return {"code": -1, "message": str(e), "data": {"data": [], "nextId": None}}
    try:
        return resp.json()
    except Exception:
        return {"code": resp.status_code, "message": resp.text[:200], "data": {"data": [], "nextId": None}}


def get_item_detail(cookies: str, item_id: int):
    url = f"https://mall.bilibili.com/mall-magic-c/internet/c2c/items/queryC2cItemsDetail?c2cItemsId={item_id}&csrf="
    headers = {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": USER_AGENT,
        "Cookie": cookies,
        "Origin": "https://mall.bilibili.com",
        "Referer": "https://mall.bilibili.com/neul-next/index.html"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
    except Exception as e:
        return {"code": -1, "message": str(e), "data": None}
    try:
        return resp.json()
    except Exception:
        text = resp.text if hasattr(resp, "text") else ""
        return {"code": resp.status_code, "message": text[:200], "data": None}


async def get_item_detail_async(cookies: str, item_id: int, timeout: float = 10) -> dict[str, Any]:
    url = f"https://mall.bilibili.com/mall-magic-c/internet/c2c/items/queryC2cItemsDetail?c2cItemsId={item_id}&csrf="
    headers = {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": USER_AGENT,
        "Cookie": cookies,
        "Origin": "https://mall.bilibili.com",
        "Referer": "https://mall.bilibili.com/neul-next/index.html",
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, headers=headers)
    except Exception as e:
        return {"code": -1, "message": str(e), "data": None}
    try:
        return resp.json()
    except Exception:
        return {"code": resp.status_code, "message": resp.text[:200], "data": None}
