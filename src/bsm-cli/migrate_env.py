import os
import sys

import yaml

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_SRC_ROOT = os.path.join(_REPO_ROOT, "src")
if _SRC_ROOT not in sys.path:
    sys.path.insert(0, _SRC_ROOT)

from bsm.settings import load_yaml_config

yd = load_yaml_config()
ytg = yd.get("telegram", {})
ytg["enabled"] = False
ytg["notify"] = False
ytg["bot_token"] = ""
ytg["chat_ids"] = []
ytg["admin_chat_ids"] = []
ytg["heartbeat_chat_ids"] = []
ytg["chat_rules_json"] = "{}"
yd["telegram"] = ytg

ynotify = yd.get("notify", {})
yemail = ynotify.get("email", {})
yemail["enabled"] = False
yemail["smtp_server"] = "smtp.qq.com"
yemail["smtp_port"] = 587
yemail["username"] = ""
yemail["password"] = ""
yemail["to"] = []

ysms = ynotify.get("sms", {})
ysms["enabled"] = False
ysms["provider"] = ""
ysms["api_key"] = ""
ysms["to"] = []

ynotify["email"] = yemail
ynotify["sms"] = ysms

yd["notify"] = ynotify

import bsm.env
path = os.path.join(bsm.env.data_dir(), "config.yaml")

with open(path, "w", encoding="utf-8") as f:
    yaml.safe_dump(yd, f, allow_unicode=True, sort_keys=False)
