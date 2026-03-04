import os
import sys
import time
import argparse
import re


def _repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _load_session():
    base = _repo_root()
    src = os.path.join(base, "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    from bsm.session import load_session
    return load_session()


def _load_config():
    base = _repo_root()
    src = os.path.join(base, "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    from bsm.settings import load_runtime_config
    return load_runtime_config()


def _state_path():
    base = _repo_root()
    return os.path.join(base, "data", "scan_state.json")


def _load_state():
    path = _state_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state: dict):
    path = _state_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)


def _item_url(iid: int) -> str:
    return f"https://mall.bilibili.com/neul-next/index.html?page=magic-market_detail&noTitleBar=1&itemsId={iid}"


def _print_qr(url: str) -> None:
    try:
        import qrcode
        from qrcode import constants
        import shutil

        qr = qrcode.QRCode(border=1, error_correction=constants.ERROR_CORRECT_M)
        qr.add_data(url)
        qr.make(fit=True)
        m = qr.get_matrix()
        h = len(m)
        w = len(m[0])
        cols = shutil.get_terminal_size(fallback=(80, 24)).columns
        left_pad = max(0, (cols - w) // 2)
        sys.stdout.write("\n")
        for y in range(0, h, 2):
            top = m[y]
            bottom = m[y + 1] if y + 1 < h else [False] * w
            line = []
            for x in range(w):
                t = top[x]
                b = bottom[x]
                if t and b:
                    ch = "█"
                elif t and not b:
                    ch = "▀"
                elif not t and b:
                    ch = "▄"
                else:
                    ch = " "
                line.append(ch)
            sys.stdout.write(" " * left_pad + "".join(line) + "\n")
        sys.stdout.write("\n")
        sys.stdout.flush()
    except Exception:
        print(url)


def _beep() -> None:
    try:
        import winsound
        winsound.Beep(900, 150)
    except Exception:
        sys.stdout.write("\a")
        sys.stdout.flush()


def _scan_once(cookies: str, cfg: dict, next_id=None):
    from bsm.mall import list_items
    from bsm.scan import DEFAULT_DISCOUNT_FILTERS, DEFAULT_PRICE_FILTERS

    pf = list(DEFAULT_PRICE_FILTERS)
    df = list(DEFAULT_DISCOUNT_FILTERS)
    result = list_items(
        cookies,
        pf,
        df,
        cfg.get("sort_type", "TIME_DESC"),
        next_id,
        cfg.get("category") or None,
    )
    code = result.get("code")
    if code == 429:
        time.sleep(5)
        return None, []
    payload = result.get("data") or {}
    items = payload.get("data") or []
    if not isinstance(items, list):
        items = []
    return payload.get("nextId"), items


def main() -> int:
    parser = argparse.ArgumentParser(prog="scan", description="BiliShareMall Scanner (atomic)")
    parser.add_argument("--mode", choices=["latest", "continue"], default=None)
    args = parser.parse_args()
    sess = _load_session()
    cookies = sess.get("cookies")
    if not cookies:
        return 1
    cfg = _load_config()
    mode = args.mode or cfg.get("scan_mode", "latest")
    st = _load_state()
    last_next = st.get("nextId") if mode == "continue" else None
    next_id, items = _scan_once(cookies, cfg, last_next)
    if mode == "continue" and next_id is not None:
        _save_state({"nextId": next_id, "page": (st.get("page", 0) + 1)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
