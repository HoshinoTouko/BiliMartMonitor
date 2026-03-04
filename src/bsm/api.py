import requests
import json

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0"


def get_login_key_and_url():
    url = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=10)
    data = resp.json()
    login_key = data.get("data", {}).get("qrcode_key", "")
    login_url = data.get("data", {}).get("url", "")
    return login_key, login_url


def _get_buvid3():
    resp = requests.get(
        "https://api.bilibili.com/x/frontend/finger/spi", headers={"User-Agent": USER_AGENT}, timeout=10
    )
    data = resp.json()
    if data.get("code") == 0:
        return data.get("data", {}).get("b_3", "")
    raise RuntimeError(data.get("message", "failed to get buvid3"))


def verify_login(login_key: str) -> str:
    poll_url = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
    params = {"qrcode_key": login_key}
    resp = requests.get(poll_url, params=params, headers={"User-Agent": USER_AGENT}, timeout=10)
    data = resp.json()
    if data.get("data", {}).get("url"):
        buvid3 = _get_buvid3()
        cookies = []
        raw = getattr(resp, "raw", None)
        if raw and hasattr(raw, "headers") and hasattr(raw.headers, "getlist"):
            cookies = raw.headers.getlist("Set-Cookie")
        else:
            sc = resp.headers.get("Set-Cookie")
            if sc:
                cookies = [sc]
        parts = [f"buvid3={buvid3}"] if buvid3 else []
        for v in cookies:
            pair = v.split(";")[0]
            if pair:
                parts.append(pair)
        return ";".join(parts) + ";"
    return ""


def get_current_login_username(cookies: str) -> str:
    if not cookies:
        return ""
    resp = requests.get(
        "https://api.bilibili.com/x/web-interface/nav",
        headers={
            "User-Agent": USER_AGENT,
            "Referer": "https://www.bilibili.com/",
            "Cookie": cookies,
        },
        timeout=10,
    )
    data = resp.json()
    payload = data.get("data") or {}
    if data.get("code") == 0 and payload.get("isLogin") is True:
        return str(payload.get("uname") or "").strip()
    return ""
