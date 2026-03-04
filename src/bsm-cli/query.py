import argparse
import os
import sys


def _src_path() -> str:
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    return os.path.join(base, "src")



def main() -> int:
    parser = argparse.ArgumentParser(prog="query", description="Query items by regex")
    parser.add_argument("pattern")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    src = _src_path()
    if src not in sys.path:
        sys.path.insert(0, src)
    from bsm.db import search_items_by_pattern

    limit = args.limit if args.limit > 0 else 100000
    items, _, _ = search_items_by_pattern(args.pattern, limit=limit, page=1)
    for item in items:
        print(f"{item['id']} | {item['name']} | {item['price']} | {item['market']} | {item['url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
