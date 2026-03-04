import os
import sys
import time
import argparse
import threading

_CONTINUE_MAX_PAGES = 50


def _repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _mode_log_label(mode: str) -> str:
    if mode == "continue_until_repeat":
        return "CUR"
    return mode


def _mode_page(mode: str, continue_page_count: int) -> int:
    if mode in {"continue", "continue_until_repeat"}:
        return continue_page_count + 1
    return 1


def _mode_semantics(mode: str, page: int) -> str:
    if mode == "latest":
        return "固定扫描第1页"
    if mode == "continue":
        return f"翻页续扫，第 {page} 页，最多 {_CONTINUE_MAX_PAGES} 页"
    if mode == "continue_until_repeat":
        return f"翻页续扫，第 {page} 页，遇重复回第1页，最多 {_CONTINUE_MAX_PAGES} 页"
    return f"第 {page} 页"


def _load_config():
    base = os.path.join(_repo_root(), "src")
    if base not in sys.path:
        sys.path.insert(0, base)
    from bsm.settings import load_runtime_config
    return load_runtime_config()


def _load_session():
    base = os.path.join(_repo_root(), "src")
    if base not in sys.path:
        sys.path.insert(0, base)
    from bsm.session import load_session
    return load_session()

def main() -> int:
    parser = argparse.ArgumentParser(prog="cron", description="BiliShareMall Cron")
    parser.add_argument("--mode", choices=["latest", "continue", "continue_until_repeat"], default=None)
    args = parser.parse_args()
    sess = _load_session()
    if not sess.get("cookies"):
        print("尚未登录，请先运行: python3 src/bsm-cli/login.py")
        return 1
    printed_ids = set()
    last_next = None
    continue_page_count = 0
    from bsm.telegrambot import bot_loop
    t = threading.Thread(target=bot_loop, daemon=True)
    t.start()
    while True:
        cfg = _load_config()
        mode = args.mode or cfg.get("scan_mode", "latest")
        interval = cfg.get("interval", 20)
        page = _mode_page(mode, continue_page_count)
        mode_label = _mode_log_label(mode)
        try:
            sess = _load_session()
            cookies = sess.get("cookies")
            if not cookies:
                print("没有可用 session，停止轮询")
                return 1
            print(
                f"开始扫描 模式 {mode_label} | 语义: {_mode_semantics(mode, page)}"
            )
            from bsm.scan import scan_once
            from bsm.db import filter_new_items, mark_bili_session_result, record_bili_session_fetch_success
            continue_like_mode = mode in {"continue", "continue_until_repeat"}
            next_id, items = scan_once(cookies, cfg, None if not continue_like_mode else last_next)
            new_items = filter_new_items(items)
            from bsm.db import save_items, count_items
            saved, inserted = save_items(items)
            if sess.get("login_username"):
                record_bili_session_fetch_success(sess["login_username"], fetched_count=len(items))
            if sess.get("login_username"):
                mark_bili_session_result(sess["login_username"], None)
            from bsm.notify import load_notifier
            notifier = load_notifier(cfg.get("notify"))
            notifier.notify_batch(new_items, cfg, printed_ids)
            total_db = count_items()
            print(
                f"扫描完成 模式 {mode_label} | 页码 {page} | 获取 {len(items)} 条 | "
                f"已保存 {saved} 条 | 新增 {inserted} 条 | 数据库合计 {total_db} 条"
            )
            should_reset_on_repeat = mode == "continue_until_repeat" and len(new_items) < len(items)
            reset_reason = ""
            if continue_like_mode:
                continue_page_count += 1
                if should_reset_on_repeat:
                    reset_reason = "遇到重复商品，下轮回到第1页"
                elif next_id is None:
                    reset_reason = "已到末页，下轮回到第1页"
                elif continue_page_count >= _CONTINUE_MAX_PAGES:
                    reset_reason = f"达到 {_CONTINUE_MAX_PAGES} 页上限，下轮回到第1页"
                if reset_reason:
                    last_next = None
                    continue_page_count = 0
                else:
                    last_next = next_id
            else:
                last_next = None
                continue_page_count = 0
                reset_reason = "固定扫描第1页"
            print(f"扫描语义 {mode_label} | {reset_reason}")
        except KeyboardInterrupt:
            try:
                from bsm.db import count_items
                print(f"已停止，数据库合计 {count_items()} 条")
            except Exception:
                print("已停止")
            return 0
        except Exception as e:
            try:
                from bsm.db import mark_bili_session_result
                if sess.get("login_username"):
                    mark_bili_session_result(sess.get("login_username"), str(e))
            except Exception:
                pass
            print(f"运行出错: {e}")
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
