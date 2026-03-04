"""
Sessions router — XHR + WebSocket dual-stack.
Routes:
  GET    /api/admin/sessions
  DELETE /api/admin/sessions/{login_username}
  WS     /api/ws/admin/sessions
"""
from __future__ import annotations

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect, Depends
from fastapi.responses import JSONResponse

from ..backend import list_bili_sessions, logout_bili_session
from backend.auth import get_current_admin

router = APIRouter(dependencies=[Depends(get_current_admin)])


# ---------------------------------------------------------------------------
# XHR endpoints
# ---------------------------------------------------------------------------

@router.get("/api/admin/sessions")
async def list_sessions_api(_: Request) -> JSONResponse:
    return JSONResponse({"sessions": list_bili_sessions()})


@router.delete("/api/admin/sessions/{login_username}")
async def delete_session_api(login_username: str) -> JSONResponse:
    logout_bili_session(login_username)
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@router.websocket("/api/ws/admin/sessions")
async def ws_admin_sessions(websocket: WebSocket) -> None:
    """WebSocket endpoint for admin session list/delete.

    Accepted message shapes (JSON):
      {"action": "list", "_id": n}
      {"action": "delete", "login_username": "...", "_id": n}
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
            if action == "list":
                await websocket.send_json({**base, "sessions": list_bili_sessions()})
            elif action == "delete":
                username = str(message.get("login_username") or "").strip()
                if username:
                    logout_bili_session(username)
                await websocket.send_json({**base, "ok": True})
            else:
                await websocket.send_json({**base, "error": f"unknown action: {action!r}"})
    except WebSocketDisconnect:
        pass
