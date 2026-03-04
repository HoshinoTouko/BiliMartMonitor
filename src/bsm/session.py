from typing import Dict, Optional

from .db import clear_bili_sessions, has_active_bili_session, load_next_bili_session, save_bili_session


def load_session() -> Dict:
    session = load_next_bili_session()
    if not session:
        return {}
    return {
        "id": session.get("id"),
        "login_username": session.get("login_username"),
        "created_by": session.get("created_by"),
        "cookies": session.get("cookies"),
        "status": session.get("status"),
    }


def save_session(
    cookies: str,
    created_by: str = "",
    login_username: str = "",
) -> None:
    save_bili_session(
        cookies=cookies,
        created_by=created_by,
        login_username=login_username,
    )


def clear_session(login_username: Optional[str] = None) -> None:
    clear_bili_sessions(login_username=login_username)


def has_session() -> bool:
    return has_active_bili_session()
