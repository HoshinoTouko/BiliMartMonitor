"""
BSM FastAPI backend — bili session / QR helpers.
Delegates to src/bsm/db and src/bsm/api (unchanged business logic).
"""
from __future__ import annotations

import base64
import io
import os
import sys
from typing import Any, Dict, List

_SRC_ROOT = os.path.dirname(os.path.dirname(__file__))
_PROJECT_ROOT = os.path.dirname(_SRC_ROOT)
if _SRC_ROOT not in sys.path:
    sys.path.insert(0, _SRC_ROOT)

from bsm import db  # noqa: E402
from bsm.api import get_current_login_username, get_login_key_and_url, verify_login  # noqa: E402


def list_bili_sessions() -> List[Dict[str, Any]]:
    sessions = db.list_bili_sessions(status=None)
    result: List[Dict[str, Any]] = []
    for session in sessions:
        result.append(
            {
                "login_username": str(session.get("login_username") or "-"),
                "created_by": str(session.get("created_by") or "-"),
                "status": str(session.get("status") or ""),
                "fetch_count": str(session.get("fetch_count") or 0),
                "login_at": str(session.get("login_at") or "-"),
                "last_success_fetch_at": str(session.get("last_success_fetch_at") or "-"),
            }
        )
    return result


def logout_bili_session(login_username: str) -> None:
    if not login_username:
        return
    db.delete_bili_session(login_username)


def create_bili_login_qr() -> Dict[str, str]:
    login_key, login_url = get_login_key_and_url()
    if not login_key or not login_url:
        return {"login_key": "", "login_url": "", "qr_image": ""}

    import qrcode

    qr = qrcode.QRCode(border=2)
    qr.add_data(login_url)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return {
        "login_key": login_key,
        "login_url": login_url,
        "qr_image": f"data:image/png;base64,{encoded}",
    }


def complete_bili_login_qr(
    login_key: str,
    created_by: str = "",
) -> Dict[str, str]:
    if not login_key:
        return {"ok": "", "login_username": ""}
    cookies = verify_login(login_key)
    if not cookies:
        return {"ok": "", "login_username": ""}
    login_username = get_current_login_username(cookies)
    if not login_username:
        return {"ok": "", "login_username": ""}
    created_by = str(created_by or "").strip() or None
    db.save_bili_session(
        cookies=cookies,
        created_by=created_by or "",
        login_username=login_username,
        status="active",
    )
    return {"ok": "1", "login_username": login_username}
