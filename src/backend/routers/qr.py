"""
QR router — XHR + WebSocket dual-stack.
Routes:
  GET  /api/admin/qr/create
  POST /api/admin/qr/poll
  WS   /api/ws/admin/qr
"""
from __future__ import annotations

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect, Depends
from fastapi.responses import JSONResponse

from ..backend import create_bili_login_qr, complete_bili_login_qr
from backend.auth import get_current_admin

router = APIRouter(dependencies=[Depends(get_current_admin)])


# ---------------------------------------------------------------------------
# XHR endpoints
# ---------------------------------------------------------------------------

@router.get("/api/admin/qr/create")
async def qr_create_api(_: Request) -> JSONResponse:
    result = create_bili_login_qr()
    return JSONResponse(result)


@router.post("/api/admin/qr/poll")
async def qr_poll_api(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "请求格式错误"}, status_code=400)
    login_key = str(body.get("login_key") or "").strip()
    created_by = str(body.get("created_by") or "").strip()
    if not login_key:
        return JSONResponse({"ok": False, "error": "login_key 不能为空"}, status_code=400)
    result = complete_bili_login_qr(login_key, created_by=created_by)
    return JSONResponse(result)


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@router.websocket("/api/ws/admin/qr")
async def ws_admin_qr(websocket: WebSocket) -> None:
    """WebSocket endpoint for QR login flow.

    Accepted message shapes (JSON):
      {"action": "create", "_id": n}
      {"action": "poll",   "login_key": "...", "created_by": "...", "_id": n}
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
            if action == "create":
                result = create_bili_login_qr()
                await websocket.send_json({**base, **result})
            elif action == "poll":
                login_key = str(message.get("login_key") or "").strip()
                created_by = str(message.get("created_by") or "").strip()
                if not login_key:
                    await websocket.send_json({**base, "ok": False, "error": "login_key 不能为空"})
                else:
                    result = complete_bili_login_qr(login_key, created_by=created_by)
                    await websocket.send_json({**base, **result})
            else:
                await websocket.send_json({**base, "error": f"unknown action: {action!r}"})
    except WebSocketDisconnect:
        pass
