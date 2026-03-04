from typing import Optional, Dict, List
import smtplib
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from bsm.telegrambot import TelegramBot
from bsm.settings import list_access_users_with_telegram


class Notifier:
    def __init__(self, cfg: Optional[Dict] = None):
        self.cfg = cfg or {}

    def email(self, subject: str, body: str, to: Optional[List[str]] = None) -> bool:
        ecfg = (self.cfg or {}).get("email", {})
        if not ecfg.get("enabled"):
            return False
        recipients = to if to else ecfg.get("to") or []
        if not recipients:
            return False
        server = ecfg.get("smtp_server") or ""
        port = int(ecfg.get("smtp_port") or 0)
        username = ecfg.get("username") or ""
        password = ecfg.get("password") or ""
        if not server or not port or not username or not password:
            return False
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = username
        msg["To"] = ", ".join(recipients)
        part_html = MIMEText(body, "html", "utf-8")
        msg.attach(part_html)
        try:
            if port == 465:
                with smtplib.SMTP_SSL(server, port) as smtp:
                    smtp.login(username, password)
                    smtp.sendmail(username, recipients, msg.as_string())
            else:
                with smtplib.SMTP(server, port) as smtp:
                    smtp.starttls()
                    smtp.login(username, password)
                    smtp.sendmail(username, recipients, msg.as_string())
            return True
        except Exception:
            return False

    def sms(self, message: str, to: Optional[str] = None) -> bool:
        scfg = (self.cfg or {}).get("sms", {})
        if not scfg.get("enabled"):
            return False
        return False

    def _item_url(self, iid: int) -> str:
        return f"https://mall.bilibili.com/neul-next/index.html?page=magic-market_detail&noTitleBar=1&itemsId={iid}"

    def _app_item_url(self, iid: int, cfg: Dict) -> str:
        base_url = str((cfg or {}).get("app_base_url") or "").strip().rstrip("/")
        if base_url:
            return f"{base_url}/market/{iid}"
        return f"/market/{iid}"

    def _beep(self) -> None:
        try:
            import winsound
            winsound.Beep(900, 150)
        except Exception:
            print("\a", end="")

    def notify_batch(self, items: List[Dict], cfg: Dict, printed_ids: set) -> int:
        beeped = False
        tg = (cfg.get("telegram") or {})
        bot: Optional[TelegramBot] = None
        if tg.get("enabled") and tg.get("notify") and tg.get("bot_token"):
            bot = TelegramBot(tg.get("bot_token"))
        access_users = list_access_users_with_telegram(status="active")
        for it in items:
            iid = it.get("c2cItemsId")
            name = it.get("c2cItemsName")
            targeted_chat_ids = self._match_target_chat_ids(name or "", access_users)
            if not targeted_chat_ids:
                continue
            if iid in printed_ids:
                continue
            if not beeped:
                self._beep()
                beeped = True
            printed_ids.add(iid)
            img = ""
            details = it.get("detailDtoList") or []
            if details:
                img = details[0].get("img") or ""
            if isinstance(img, str) and img.startswith("//"):
                img = "https:" + img
            uname = it.get("uname") or ""
            market = it.get("showMarketPrice") or ""
            link = self._item_url(iid)
            app_link = self._app_item_url(iid, cfg)
            if bot:
                caption = (
                    f"ID: {iid}\n名称: {name}\n发布人: {uname}\n价格: {it.get('showPrice')}\n"
                    f"总价: {market}\n应用内查看: {app_link}\nB站原链接: {link}"
                )
                for chat_id in targeted_chat_ids:
                    if img:
                        bot.send_photo_to(chat_id, img, caption)
                    else:
                        bot.send_text_to(chat_id, caption)
        return 0

    def _match_target_chat_ids(self, item_name: str, access_users: List[Dict]) -> List[str]:
        matched: List[str] = []
        for user in access_users:
            if not bool(user.get("notify_enabled", True)):
                continue
            chat_ids = [str(chat_id).strip() for chat_id in (user.get("telegram_ids") or []) if str(chat_id).strip()]
            if not chat_ids:
                continue
            keywords = user.get("keywords") or []
            if not keywords:
                continue
            for keyword in keywords:
                try:
                    if re.search(str(keyword), item_name):
                        matched.extend(chat_ids)
                        break
                except Exception:
                    continue
        return sorted(set(matched))


def load_notifier(cfg: Optional[Dict] = None) -> Notifier:
        return Notifier(cfg)


def send_admin_telegram_alert(message: str, cfg: Optional[Dict] = None) -> int:
    from bsm.settings import load_runtime_config

    runtime_cfg = cfg or load_runtime_config()
    admin_ids = [str(item).strip() for item in (runtime_cfg.get("admin_telegram_ids") or []) if str(item).strip()]
    tg = runtime_cfg.get("telegram") or {}
    token = str(tg.get("bot_token") or "").strip()
    if not admin_ids or not token:
        return 0

    bot = TelegramBot(token)
    sent = 0
    for chat_id in sorted(set(admin_ids)):
        if bot.send_text_to(chat_id, message):
            sent += 1
    return sent
