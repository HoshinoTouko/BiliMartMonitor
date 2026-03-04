import os
import sys


def main() -> int:
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    src = os.path.join(base, "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    from bsm.cli import cmd_login
    return cmd_login()


if __name__ == "__main__":
    raise SystemExit(main())
