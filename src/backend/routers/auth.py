"""
Auth router — XHR + WebSocket dual-stack.
Routes:
  GET  /api/auth/me
  POST /api/auth/login
  POST /api/auth/logout
  WS   /api/ws/auth
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from ..auth import (
    authenticate_credentials,
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    clear_failed_auth_attempts,
    create_session_token,
    get_client_ip,
    get_current_user,
    record_failed_auth_attempt,
    reject_if_banned,
    verify_cloudflare_token,
)

router = APIRouter()


def _role_redirect(role: str) -> str:
    if role == "admin":
        return "/admin"
    if role == "user":
        return "/app"
    return "/"


# ---------------------------------------------------------------------------
# XHR endpoints
# ---------------------------------------------------------------------------


def _request_is_secure(request: Request) -> bool:
    proto = str(request.headers.get("x-forwarded-proto") or "").strip().lower()
    if proto:
        return proto == "https"
    return request.url.scheme == "https"


@router.post("/api/auth/login")
async def login_api(request: Request) -> JSONResponse:
    client_ip = get_client_ip(request)
    blocked = reject_if_banned(client_ip)
    if blocked:
        return JSONResponse({"ok": False, "error": blocked.detail}, status_code=blocked.status_code)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "请求格式错误"}, status_code=400)
    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "").strip()
    cf_token = str(body.get("cf_token") or "").strip()
    verified, verify_error = verify_cloudflare_token(cf_token, client_ip)
    if not verified:
        status_code = 503 if "not configured" in verify_error else 403
        return JSONResponse({"ok": False, "error": verify_error}, status_code=status_code)
    result = authenticate_credentials(username, password)
    if result is None:
        blocked = record_failed_auth_attempt(client_ip, username)
        if blocked:
            return JSONResponse({"ok": False, "error": blocked.detail}, status_code=blocked.status_code)
        return JSONResponse({"ok": False, "error": "用户名或密码错误"}, status_code=401)
    uname, role = result
    clear_failed_auth_attempts(client_ip)
    response = JSONResponse({
        "ok": True,
        "username": uname,
        "role": role,
        "redirect": _role_redirect(role),
    })
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=create_session_token(uname),
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=_request_is_secure(request),
        path="/",
    )
    return response


@router.get("/api/auth/me")
async def me_api(user=Depends(get_current_user)) -> JSONResponse:
    return JSONResponse({
        "ok": True,
        "username": str(user.get("username") or ""),
        "role": str(user.get("role") or "guest"),
        "display_name": str(user.get("display_name") or ""),
    })


@router.post("/api/auth/logout")
async def logout_api(_: Request) -> JSONResponse:
    response = JSONResponse({"ok": True})
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    return response


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@router.websocket("/api/ws/auth")
async def ws_auth(websocket: WebSocket) -> None:
    """WebSocket endpoint for auth actions.

    Accepted message shapes (JSON):
      {"action": "login",  "username": "...", "password": "...", "_id": n}
      {"action": "logout", "_id": n}
    """
    await websocket.accept()
    try:
        while True:
            try:
                message = await websocket.receive_json()
            except Exception:
                break
            action = (message.get("action") or "").strip()
            _id = message.get("_id")
            base = {"_id": _id} if _id is not None else {}
            if action == "login":
                client_ip = get_client_ip(websocket)
                blocked = reject_if_banned(client_ip)
                if blocked:
                    await websocket.send_json({**base, "ok": False, "error": blocked.detail})
                    continue
                username = str(message.get("username") or "").strip()
                password = str(message.get("password") or "").strip()
                cf_token = str(message.get("cf_token") or "").strip()
                verified, verify_error = verify_cloudflare_token(cf_token, client_ip)
                if not verified:
                    await websocket.send_json({**base, "ok": False, "error": verify_error})
                    continue
                result = authenticate_credentials(username, password)
                if result is None:
                    blocked = record_failed_auth_attempt(client_ip, username)
                    if blocked:
                        await websocket.send_json({**base, "ok": False, "error": blocked.detail})
                    else:
                        await websocket.send_json({**base, "ok": False, "error": "用户名或密码错误"})
                else:
                    clear_failed_auth_attempts(client_ip)
                    uname, role = result
                    await websocket.send_json({
                        **base,
                        "ok": True,
                        "username": uname,
                        "role": role,
                        "redirect": _role_redirect(role),
                    })
            elif action == "logout":
                await websocket.send_json({**base, "ok": True})
            else:
                await websocket.send_json({**base, "error": f"unknown action: {action!r}"})
    except WebSocketDisconnect:
        pass
