import time
import asyncio
import logging
from typing import Dict, Any, List, Optional

from bsm.db import search_items_by_pattern, upsert_access_user
from bsm.settings import load_runtime_config, list_runtime_settings, set_mode, get_access_user_by_telegram_id, get_access_user

log = logging.getLogger("bsm.telegram")

# Username -> (code, expiry)
PENDING_BINDS: Dict[str, tuple[str, float]] = {}
PENDING_BIND_TTL_SECONDS = 600
UPDATE_EVENT = asyncio.Event()

def trigger_bot_update():
    UPDATE_EVENT.set()


def prune_expired_binds(now: Optional[float] = None) -> None:
    if not PENDING_BINDS:
        return
    cutoff = time.time() if now is None else now
    expired_users = [
        username
        for username, (_, expiry) in list(PENDING_BINDS.items())
        if expiry <= cutoff
    ]
    for username in expired_users:
        PENDING_BINDS.pop(username, None)


def _state_path() -> str:
    base = os.path.dirname(__file__)
    return os.path.join(os.path.abspath(os.path.join(base, os.pardir)), "data", "scan_state.json")


def list_settings() -> Dict[str, Any]:
    return list_runtime_settings()


def reset_progress() -> None:
    with open(_state_path(), "w", encoding="utf-8") as f:
        json.dump({"nextId": None, "page": 0}, f, ensure_ascii=False)


def query_db(pattern: str, limit: int = 50) -> List[Dict[str, Any]]:
    items, _, _ = search_items_by_pattern(pattern, limit=limit, page=1)
    return items


def query_db_paginated(pattern: str, limit: int, page: int) -> List[Any]:
    items, total_count, total_pages = search_items_by_pattern(pattern, limit=limit, page=page)
    page = max(1, page)
    has_prev = page > 1 and total_pages > 0
    has_next = page < total_pages
    return [items, has_prev, has_next, total_count, total_pages]


class TelegramBot:
    def __init__(self, token: str, chat_id: Optional[str] = None):
        self.token = token
        self.chat_id = chat_id

    def send_text(self, text: str) -> bool:
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            data = {"chat_id": self.chat_id, "text": text}
            r = requests.post(url, data=data, timeout=10)
            return bool(r.ok)
        except Exception:
            return False

    def send_text_to(self, chat_id: str, text: str) -> bool:
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            data = {"chat_id": chat_id, "text": text}
            r = requests.post(url, data=data, timeout=10)
            return bool(r.ok)
        except Exception:
            return False

    def send_photo(self, photo_url: str, caption: str) -> bool:
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendPhoto"
            data = {"chat_id": self.chat_id, "photo": photo_url, "caption": caption}
            r = requests.post(url, data=data, timeout=10)
            return bool(r.ok)
        except Exception:
            return False

    def send_photo_to(self, chat_id: str, photo_url: str, caption: str) -> bool:
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendPhoto"
            data = {"chat_id": chat_id, "photo": photo_url, "caption": caption}
            r = requests.post(url, data=data, timeout=10)
            return bool(r.ok)
        except Exception:
            return False

    def send_text_markup(self, text: str, reply_markup: Optional[Dict[str, Any]]) -> bool:
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            data = {"chat_id": self.chat_id, "text": text}
            if reply_markup:
                data["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
            r = requests.post(url, data=data, timeout=10)
            return bool(r.ok)
        except Exception:
            return False

    def send_text_markup_to(self, chat_id: str, text: str, reply_markup: Optional[Dict[str, Any]]) -> bool:
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            data = {"chat_id": chat_id, "text": text}
            if reply_markup:
                data["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
            r = requests.post(url, data=data, timeout=10)
            return bool(r.ok)
        except Exception:
            return False

    def send_items(self, items: List[Dict[str, Any]]) -> bool:
        try:
            if not items:
                return self.send_text("未找到结果")
            lines = []
            for it in items:
                lines.append(f"{it['id']} | {it['name']} | {it['price']} | {it['market']} | {it['url']}")
            text = "\n".join(lines)
            if len(text) <= 3900:
                return self.send_text(text)
            idx = 0
            ok = True
            while idx < len(lines):
                chunk = []
                size = 0
                while idx < len(lines) and size + len(lines[idx]) + 1 <= 3900:
                    chunk.append(lines[idx])
                    size += len(lines[idx]) + 1
                    idx += 1
                ok = self.send_text("\n".join(chunk)) and ok
            return ok
        except Exception:
            return False

    def send_items_paginated(self, chat_id: str, items: List[Dict[str, Any]], pattern: str, limit: int, page: int, has_prev: bool, has_next: bool, total_count: int, total_pages: int) -> bool:
        try:
            lines = []
            for it in items:
                lines.append(f"{it['id']} | {it['name']} | {it['price']} | {it['market']} | {it['url']}")
            header = f"共{total_count}条 | 第{page}/{total_pages}页 | 每页{limit}"
            body = "\n".join(lines) if lines else "未找到结果"
            text = f"{header}\n{body}"
            buttons = []
            if has_prev:
                buttons.append({"text": f"上一页 ({max(1, page-1)}/{total_pages})", "callback_data": f"search|{pattern}|{limit}|{max(1, page-1)}"})
            if has_next:
                buttons.append({"text": f"下一页 ({page+1}/{total_pages})", "callback_data": f"search|{pattern}|{limit}|{page+1}"})
            markup = {"inline_keyboard": [buttons]} if buttons else None
            return self.send_text_markup_to(chat_id, text, markup)
        except Exception:
            return False

    def get_updates(self, offset: Optional[int] = None) -> List[Dict[str, Any]]:
        try:
            url = f"https://api.telegram.org/bot{self.token}/getUpdates"
            params = {"timeout": 30}
            if offset is not None:
                params["offset"] = offset
            r = requests.get(url, params=params, timeout=35)
            data = r.json()
            return data.get("result") or []
        except Exception:
            return []
    def answer_callback(self, callback_id: str) -> bool:
        try:
            url = f"https://api.telegram.org/bot{self.token}/answerCallbackQuery"
            data = {"callback_query_id": callback_id}
            r = requests.post(url, data=data, timeout=10)
            return bool(r.ok)
        except Exception:
            return False
import requests

async def bot_loop():
    offset: Optional[int] = None
    connected = False
    last_chat = None
    
    log.info("Telegram bot loop started")
    
    while True:
        try:
            prune_expired_binds()
            cfg = load_runtime_config()
            tg = cfg.get("telegram", {})
            
            if not tg.get("enabled") or not tg.get("bot_token"):
                if connected:
                    log.info("Telegram bot disabled")
                connected = False
                await asyncio.sleep(5)
                continue
            
            from bsm.settings import list_access_users_with_telegram
            access_users = list_access_users_with_telegram(status="active")
            
            chat_ids = []
            admin_chat_ids = set()
            for user in access_users:
                tids = user.get("telegram_ids") or []
                chat_ids.extend([str(t) for t in tids if str(t)])
                if "admin" in (user.get("roles") or []):
                    admin_chat_ids.update([str(t) for t in tids if str(t)])
            
            bot = TelegramBot(tg.get("bot_token"))
            
            # Initial connect or chat_ids change
            curr_chat_str = ",".join(sorted(set(chat_ids)))
            if not connected or last_chat != curr_chat_str:
                log.info(f"Telegram bot active. Monitored chat_ids: {curr_chat_str}")
                connected = True
                last_chat = curr_chat_str

            # Fetch updates
            updates = await asyncio.to_thread(bot.get_updates, offset)
            for upd in updates:
                offset = (upd.get("update_id") or 0) + 1
                
                # Handle callback queries (pagination)
                cb = upd.get("callback_query") or {}
                if cb:
                    msg = cb.get("message") or {}
                    chat_id = str(msg.get("chat", {}).get("id", ""))
                    if chat_id in chat_ids:
                        data = (cb.get("data") or "").strip()
                        parts = data.split("|")
                        if parts and parts[0] == "search" and len(parts) >= 4:
                            pattern, limit, page = parts[1], int(parts[2]), int(parts[3])
                            items, has_prev, has_next, count, total_pages = await asyncio.to_thread(
                                query_db_paginated,
                                pattern,
                                limit,
                                page,
                            )
                            await asyncio.to_thread(
                                bot.send_items_paginated,
                                chat_id,
                                items,
                                pattern,
                                limit,
                                page,
                                has_prev,
                                has_next,
                                count,
                                total_pages,
                            )
                    await asyncio.to_thread(bot.answer_callback, cb.get("id") or "")
                    continue

                # Handle messages
                msg = upd.get("message") or {}
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text = (msg.get("text") or "").strip()
                if not text or not chat_id:
                    continue

                parts = text.split()
                cmd = parts[0].lower()
                
                # 1. SPECIAL COMMAND: /bind (Allows ANY chat_id to try and bind)
                if cmd == "/bind" and len(parts) >= 2:
                    code = parts[1].strip()
                    found_user = None
                    now = time.time()
                    prune_expired_binds(now)
                    for uname, (p_code, p_expiry) in list(PENDING_BINDS.items()):
                        if p_code == code and p_expiry > now:
                            found_user = uname
                            break
                    
                    if found_user:
                        user = await asyncio.to_thread(get_access_user, found_user)
                        if user:
                            tids = set(user.get("telegram_ids") or [])
                            tids.add(chat_id)
                            await asyncio.to_thread(
                                upsert_access_user,
                                username=found_user,
                                display_name=user.get("display_name") or "",
                                password_hash=user.get("password_hash") or "",
                                telegram_ids=list(tids),
                                keywords=user.get("keywords") or [],
                                roles=user.get("roles") or [],
                                status=user.get("status") or "active",
                                notify_enabled=user.get("notify_enabled", True)
                            )
                            del PENDING_BINDS[found_user]
                            await asyncio.to_thread(bot.send_text_to, chat_id, f"✅ 绑定成功！欢迎 {found_user}。")
                            log.info(f"User {found_user} bound to telegram chat {chat_id}")
                            # chat_ids changed, loop will pick it up next time
                        else:
                            await asyncio.to_thread(bot.send_text_to, chat_id, "❌ 绑定失败：用户不存在。")
                    else:
                        await asyncio.to_thread(bot.send_text_to, chat_id, "❌ 绑定失败：验证码错误或已过期。")
                    continue

                # 2. RESTRICTED COMMANDS (Must be already bound)
                if chat_id not in chat_ids:
                    continue
                
                access_user = await asyncio.to_thread(get_access_user_by_telegram_id, chat_id)
                is_admin = chat_id in admin_chat_ids or (access_user and "admin" in (access_user.get("roles") or []))

                if cmd in ("/status", "/settings"):
                    await asyncio.to_thread(
                        bot.send_text_to,
                        chat_id,
                        json.dumps(list_settings(), ensure_ascii=False),
                    )
                elif cmd == "/setmode" and len(parts) >= 2:
                    if not is_admin:
                        await asyncio.to_thread(bot.send_text_to, chat_id, "❌ 无权限。")
                        continue
                    ok = await asyncio.to_thread(set_mode, parts[1])
                    await asyncio.to_thread(bot.send_text_to, chat_id, "✅ 已切换" if ok else "❌ 切换失败")
                elif cmd == "/reset":
                    if not is_admin:
                        await asyncio.to_thread(bot.send_text_to, chat_id, "❌ 无权限。")
                        continue
                    await asyncio.to_thread(reset_progress)
                    await asyncio.to_thread(bot.send_text_to, chat_id, "✅ 进度已重置")
                elif cmd == "/search" and len(parts) >= 2:
                    pattern = parts[1]
                    limit = int(parts[2]) if len(parts) >= 3 else 10
                    page = int(parts[3]) if len(parts) >= 4 else 1
                    items, has_prev, has_next, count, total_pages = await asyncio.to_thread(
                        query_db_paginated,
                        pattern,
                        limit,
                        page,
                    )
                    await asyncio.to_thread(
                        bot.send_items_paginated,
                        chat_id,
                        items,
                        pattern,
                        limit,
                        page,
                        has_prev,
                        has_next,
                        count,
                        total_pages,
                    )

            # Wait for next poll or trigger
            poll_interval = tg.get("poll_interval", 10)
            try:
                await asyncio.wait_for(UPDATE_EVENT.wait(), timeout=poll_interval)
                UPDATE_EVENT.clear()
            except asyncio.TimeoutError:
                pass

        except asyncio.CancelledError:
            log.info("Telegram bot loop stopping...")
            break
        except Exception as e:
            log.error(f"Telegram bot error: {e}")
            await asyncio.sleep(10)
