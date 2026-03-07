import argparse
import gzip
import json
import os
import sys
from typing import Any, Dict, List, Optional


def _src_path() -> str:
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    return os.path.join(base, "src")


def _decode_detail_blob(detail_blob: Any) -> List[Dict[str, Any]]:
    if not detail_blob:
        return []
    try:
        return json.loads(gzip.decompress(bytes(detail_blob)).decode("utf-8"))
    except Exception:
        return []


def _parse_detail_list(detail_blob: Any) -> List[Dict[str, Any]]:
    parsed = _decode_detail_blob(detail_blob)
    return parsed if parsed else []


def _encode_detail_blob(detail_list: List[Dict[str, Any]]) -> bytes:
    raw = json.dumps(detail_list, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return gzip.compress(raw, compresslevel=6)


def _to_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(prog="migrate-product-snapshot", description="Backfill product + c2c_items_snapshot")
    parser.add_argument("--reset", action="store_true", help="truncate product and c2c_items_snapshot before backfill")
    args = parser.parse_args()

    src = _src_path()
    if src not in sys.path:
        sys.path.insert(0, src)

    from sqlalchemy import select

    from bsm.db import _now, _require_sqlalchemy_backend
    from bsm.orm_models import C2CItem, C2CItemSnapshot, Product

    backend = _require_sqlalchemy_backend()

    migrated_product = 0
    migrated_snapshot = 0
    skipped_without_triple = 0
    blob_backfilled = 0

    with backend.session() as session:
        if args.reset:
            session.query(C2CItemSnapshot).delete()
            session.query(Product).delete()

        rows = session.scalars(select(C2CItem)).all()

        for row in rows:
            detail_list = _parse_detail_list(row.detail_blob)
            if not detail_list:
                continue
            if row.detail_blob is None:
                row.detail_blob = _encode_detail_blob(detail_list)
                blob_backfilled += 1
            snapshot_at = row.updated_at or row.created_at or _now()
            total_market = 0
            for item in detail_list:
                val = _to_int(item.get("marketPrice"))
                total_market += int(val or 0)

            for item in detail_list:
                items_id = _to_int(item.get("itemsId"))
                if items_id is None:
                    continue
                blindbox_id = _to_int(item.get("blindBoxId"))
                sku_id = _to_int(item.get("skuId"))
                if blindbox_id is None:
                    blindbox_id = 0
                if sku_id is None:
                    sku_id = 0
                market_price = _to_int(item.get("marketPrice")) or 0
                est_price = None
                if row.price is not None and total_market > 0:
                    try:
                        est_price = int(float(row.price) * float(market_price) / float(total_market))
                    except Exception:
                        est_price = None

                product = session.scalar(
                    select(Product).where(
                        Product.blindbox_id == blindbox_id,
                        Product.items_id == items_id,
                        Product.sku_id == sku_id,
                    )
                )
                if product is None:
                    product = Product(
                        blindbox_id=blindbox_id,
                        items_id=items_id,
                        sku_id=sku_id,
                        created_at=_now(),
                    )
                    session.add(product)
                    session.flush()
                    migrated_product += 1
                product.name = item.get("name", product.name)
                product.img_url = (item.get("img") or item.get("imgUrl") or item.get("image") or product.img_url)
                product.market_price = market_price
                product.updated_at = _now()
                session.add(
                    C2CItemSnapshot(
                        c2c_items_id=int(row.c2c_items_id),
                        snapshot_at=str(snapshot_at),
                        product_id=int(product.id),
                        est_price=est_price,
                    )
                )
                migrated_snapshot += 1

    print(
        json.dumps(
            {
                "reset": args.reset,
                "product_inserted": migrated_product,
                "snapshot_from_detail_blob": migrated_snapshot,
                "snapshot_skipped_without_triple": skipped_without_triple,
                "detail_blob_backfilled": blob_backfilled,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
