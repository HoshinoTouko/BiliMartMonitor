import sys
import os
import json
from pathlib import Path

_SRC_ROOT = str(Path(__file__).resolve().parent.parent / "src")
if _SRC_ROOT not in sys.path:
    sys.path.insert(0, _SRC_ROOT)

from bsm.db import _extract_img_from_detail_json, _require_sqlalchemy_backend, _utc_cutoff
from bsm.orm_models import C2CItem, C2CItemDetail

def run_backfill():
    backend = _require_sqlalchemy_backend()
    cutoff = _utc_cutoff(days=15)
    inserted = 0
    with backend.session() as session:
        session.query(C2CItemDetail).delete()
        rows = (
            session.query(C2CItem.c2c_items_id, C2CItem.detail_json, C2CItem.updated_at, C2CItem.created_at)
            .filter(C2CItem.updated_at >= cutoff)
            .all()
        )

        total = len(rows)
        print(f"Found {total} records from the last 15 days to backfill.")

        detail_models = []
        for c2c_items_id, detail_json, updated_at, created_at in rows:
            try:
                detail_list = json.loads(detail_json)
                if not isinstance(detail_list, list):
                    continue
                snapshot_at = updated_at or created_at or _utc_cutoff(seconds=0)
                for d_item in detail_list:
                    items_id = d_item.get("itemsId")
                    if items_id:
                        detail_models.append(
                            C2CItemDetail(
                                c2c_items_id=int(c2c_items_id),
                                items_id=int(items_id),
                                name=d_item.get("name", ""),
                                img_url=_extract_img_from_detail_json(json.dumps([d_item])),
                                market_price=d_item.get("marketPrice", 0),
                                snapshot_at=snapshot_at,
                            )
                        )
                        inserted += 1
            except Exception as e:
                print(f"Error parsing json for item {c2c_items_id}: {e}")

        if detail_models:
            session.add_all(detail_models)

    print(f"Backfill complete! Inserted {inserted} detail records.")

if __name__ == "__main__":
    run_backfill()
