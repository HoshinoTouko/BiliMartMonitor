import argparse
import json
import os
import sys
from typing import Any, Dict

import sqlalchemy as sa


def _src_path() -> str:
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    return os.path.join(base, "src")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="normalize-detail-blob-storage",
        description="Normalize c2c_items.detail_blob TEXT rows to real BLOB bytes",
    )
    parser.add_argument("--batch-size", type=int, default=1000, help="Rows per batch (default: 1000)")
    parser.add_argument("--max-rows", type=int, default=0, help="Max rows to process (0 means all)")
    parser.add_argument("--dry-run", action="store_true", help="Only count convertible rows; do not write")
    args = parser.parse_args()

    src = _src_path()
    if src not in sys.path:
        sys.path.insert(0, src)

    from bsm.db import _decode_detail_blob_with_reason, _encode_detail_blob, _require_sqlalchemy_backend

    batch_size = max(1, int(args.batch_size or 1000))
    max_rows = max(0, int(args.max_rows or 0))
    backend = _require_sqlalchemy_backend()

    processed = 0
    converted = 0
    skipped = 0
    reason_counts: Dict[str, int] = {}
    after_id = 0

    with backend.session() as session:
        while True:
            params: Dict[str, Any] = {"limit": batch_size}
            if max_rows > 0:
                remaining = max_rows - processed
                if remaining <= 0:
                    break
                params["limit"] = min(batch_size, remaining)
            params["after_id"] = after_id

            rows = session.execute(
                sa.text(
                    f"""
                    SELECT c2c_items_id, detail_blob
                    FROM c2c_items
                    WHERE detail_blob IS NOT NULL
                      AND typeof(detail_blob) = 'text'
                      AND c2c_items_id > :after_id
                    ORDER BY c2c_items_id ASC
                    LIMIT :limit
                    """
                ),
                params,
            ).mappings().all()

            if not rows:
                break

            for row in rows:
                cid = int(row["c2c_items_id"])
                after_id = cid
                text_value = row["detail_blob"]
                processed += 1
                parsed, reason = _decode_detail_blob_with_reason(text_value)
                if not parsed:
                    skipped += 1
                    key = reason or "unknown"
                    reason_counts[key] = reason_counts.get(key, 0) + 1
                    continue
                converted += 1
                if args.dry_run:
                    continue
                blob_hex = _encode_detail_blob(parsed).hex()
                session.execute(
                    sa.text(
                        f"""
                        UPDATE c2c_items
                        SET detail_blob = X'{blob_hex}'
                        WHERE c2c_items_id = :cid
                        """
                    ),
                    {"cid": cid},
                )

    print(
        json.dumps(
            {
                "dry_run": bool(args.dry_run),
                "processed_text_rows": processed,
                "converted_to_blob": converted,
                "skipped_unparseable": skipped,
                "skip_reasons": reason_counts,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
