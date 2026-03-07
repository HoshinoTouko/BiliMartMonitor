import argparse
import json
import os
import sys


def _src_path() -> str:
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    return os.path.join(base, "src")


def main() -> int:
    parser = argparse.ArgumentParser(prog="db-size", description="Database size diagnostics")
    parser.add_argument("--days", type=int, default=7, help="Recent window in days (default: 7)")
    parser.add_argument("--top", type=int, default=20, help="How many top tables to return (default: 20)")
    args = parser.parse_args()

    src = _src_path()
    if src not in sys.path:
        sys.path.insert(0, src)

    try:
        from bsm.db import get_database_size_report
    except Exception as exc:
        print(f"failed to load database backend: {exc}", file=sys.stderr)
        print("hint: set BSM_DB_BACKEND=sqlite when running local diagnostics.", file=sys.stderr)
        return 2

    try:
        report = get_database_size_report(days=args.days, top_n=args.top)
    except Exception as exc:
        print(f"failed to run diagnostics: {exc}", file=sys.stderr)
        print("hint: set BSM_DB_BACKEND=sqlite when running local diagnostics.", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
