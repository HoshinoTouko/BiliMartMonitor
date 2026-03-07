import gzip
import json
import sys
from pathlib import Path

_SRC_ROOT = str(Path(__file__).resolve().parent.parent / "src")
if _SRC_ROOT not in sys.path:
    sys.path.insert(0, _SRC_ROOT)

from bsm.db import _encode_detail_blob, _now, _require_sqlalchemy_backend, _utc_cutoff
from bsm.orm_models import C2CItem, C2CItemSnapshot, Product


def _parse_detail_list(detail_blob):
    if detail_blob:
        try:
            data = json.loads(gzip.decompress(bytes(detail_blob)).decode("utf-8"))
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return []


def run_backfill() -> None:
    backend = _require_sqlalchemy_backend()
    cutoff = _utc_cutoff(days=15)
    inserted_snapshot = 0
    upserted_product = 0

    with backend.session() as session:
        session.query(C2CItemSnapshot).delete()

        rows = (
            session.query(
                C2CItem.c2c_items_id,
                C2CItem.price,
                C2CItem.updated_at,
                C2CItem.created_at,
                C2CItem.detail_blob,
            )
            .filter(C2CItem.updated_at >= cutoff)
            .all()
        )

        total = len(rows)
        print(f"Found {total} records from the last 15 days to backfill.")

        for c2c_items_id, c2c_price, updated_at, created_at, detail_blob in rows:
            detail_list = _parse_detail_list(detail_blob)
            if not detail_list:
                continue

            if detail_blob is None:
                try:
                    row = session.query(C2CItem).filter(C2CItem.c2c_items_id == c2c_items_id).first()
                    if row is not None:
                        row.detail_blob = _encode_detail_blob(detail_list)
                except Exception:
                    pass

            snapshot_at = updated_at or created_at or _now()
            total_market = 0
            for d_item in detail_list:
                try:
                    total_market += int(d_item.get("marketPrice", 0) or 0)
                except Exception:
                    continue

            for d_item in detail_list:
                try:
                    items_id = int(d_item.get("itemsId"))
                except Exception:
                    continue
                try:
                    blindbox_id = int(d_item.get("blindBoxId")) if d_item.get("blindBoxId") is not None else 0
                except Exception:
                    blindbox_id = 0
                try:
                    sku_id = int(d_item.get("skuId")) if d_item.get("skuId") is not None else 0
                except Exception:
                    sku_id = 0
                try:
                    market_price = int(d_item.get("marketPrice", 0) or 0)
                except Exception:
                    market_price = 0

                product = session.query(Product).filter(
                    Product.blindbox_id == blindbox_id,
                    Product.items_id == items_id,
                    Product.sku_id == sku_id,
                ).first()
                if product is None:
                    product = Product(
                        blindbox_id=blindbox_id,
                        items_id=items_id,
                        sku_id=sku_id,
                        created_at=_now(),
                    )
                    session.add(product)
                    session.flush()
                    upserted_product += 1

                product.name = d_item.get("name", product.name)
                product.img_url = d_item.get("img") or d_item.get("imgUrl") or d_item.get("image") or product.img_url
                product.market_price = market_price
                product.updated_at = _now()

                est_price = None
                if c2c_price is not None and total_market > 0:
                    try:
                        est_price = int(float(c2c_price) * float(market_price) / float(total_market))
                    except Exception:
                        est_price = None

                session.add(
                    C2CItemSnapshot(
                        c2c_items_id=int(c2c_items_id),
                        snapshot_at=str(snapshot_at),
                        product_id=int(product.id),
                        est_price=est_price,
                    )
                )
                inserted_snapshot += 1

    print(f"Backfill complete! Inserted {inserted_snapshot} snapshot records, upserted {upserted_product} products.")


if __name__ == "__main__":
    run_backfill()
