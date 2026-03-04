import argparse
import sys
import time

try:
    from .api import get_current_login_username, get_login_key_and_url, verify_login
    from .session import save_session, load_session, has_session, clear_session
except Exception:
    from api import get_current_login_username, get_login_key_and_url, verify_login
    from session import save_session, load_session, has_session, clear_session


def _print_qr(url: str) -> None:
    try:
        import qrcode
        from qrcode import constants
        import shutil

        qr = qrcode.QRCode(border=1, error_correction=constants.ERROR_CORRECT_M)
        qr.add_data(url)
        qr.make(fit=True)
        m = qr.get_matrix()
        height = len(m)
        width = len(m[0])
        cols = shutil.get_terminal_size(fallback=(80, 24)).columns
        left_pad = max(0, (cols - width) // 2)
        sys.stdout.write("\n")
        for y in range(0, height, 2):
            top = m[y]
            bottom = m[y + 1] if y + 1 < height else [False] * width
            line = []
            for x in range(width):
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
        return
    except Exception:
        print("未检测到二维码库，建议安装: py -3 -m pip install qrcode[pil]")
    print(url)


def cmd_login(created_by: str = "") -> int:
    key, url = get_login_key_and_url()
    if not key or not url:
        print("获取二维码失败")
        return 1
    _print_qr(url)
    while True:
        try:
            cookies = verify_login(key)
            if cookies:
                login_username = get_current_login_username(cookies)
                if not login_username:
                    print("登录成功，但未获取到 B 站用户名")
                    return 1
                save_session(
                    cookies,
                    created_by=created_by,
                    login_username=login_username,
                )
                print(f"登录成功: {login_username}")
                return 0
        except Exception:
            time.sleep(3)
            continue
        time.sleep(3)


def cmd_status() -> int:
    if has_session():
        data = load_session()
        print("已登录")
        print(data.get("cookies", ""))
        return 0
    print("未登录")
    return 0


def cmd_logout() -> int:
    clear_session()
    print("已登出")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="bsm", description="BiliShareMall CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)
    login_parser = sub.add_parser("login")
    login_parser.add_argument("--created-by", default="")
    sub.add_parser("status")
    sub.add_parser("logout")
    args = parser.parse_args()
    if args.cmd == "login":
        return cmd_login(created_by=args.created_by)
    if args.cmd == "status":
        return cmd_status()
    if args.cmd == "logout":
        return cmd_logout()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
