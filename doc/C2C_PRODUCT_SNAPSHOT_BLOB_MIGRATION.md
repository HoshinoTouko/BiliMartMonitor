# C2C Product/Snapshot + BLOB Migration (Final State)

## Scope
This document records the completed migration from legacy detail storage and history models to the new product/snapshot model.

## Final Data Model

### c2c_items
- Keeps listing-level fields.
- Stores bundled payload as `detail_blob` (gzip JSON bytes).
- Removed fields:
  - `detail_json`
  - `detail_codec`

### product
- Primary key: `id`.
- Unique key: `(blindbox_id, items_id, sku_id)`.
- Stores normalized component metadata:
  - `blindbox_id`, `items_id`, `sku_id`
  - `name`, `img_url`, `market_price`

### c2c_items_snapshot
- Stores per-scan snapshot rows.
- Columns:
  - `c2c_items_id`
  - `snapshot_at`
  - `product_id` (FK -> `product.id`)
  - `est_price`
- No duplicated `name/img/market_price/triple` columns.

## Removed Legacy Tables
- `c2c_items_details`
- `c2c_price_history`

## API Finalization
- Kept:
  - `GET /api/product/{sku_id}/price-history`
- Removed:
  - `GET /api/market/items/{item_id}/price-history`
  - `GET /api/market/product/{items_id}/price-history`

## Runtime Behavior
1. Scan writes/updates `c2c_items`.
2. Parse `detailDtoList` and upsert `product` by `(blindbox_id, items_id, sku_id)`.
3. Write proportional price snapshot rows to `c2c_items_snapshot` with `product_id` FK.
4. Read paths for market/product listing/history use `product + c2c_items_snapshot`.

## Frontend Behavior
- Market detail page title section shows IDs on one line:
  - `盲盒ID | Item ID | SKU ID`
- Price history calls are sku-based only.

## Migration Files
- `e1a5c9d2b741_add_product_snapshot_and_blob_columns.py`
- `5fd1b9c2a77a_drop_market_price_from_c2c_item_snapshot.py`
- `9b2c7d4e1a11_drop_detail_json_from_c2c_items.py`
- `a3d9f6c2b781_drop_detail_codec_from_c2c_items.py`
- `b4e1a2d9c6f3_drop_c2c_items_details_table.py`
- `c7f4a1e9d2b0_drop_c2c_price_history_table.py`

## Operational Note
`./scripts/run-backend.sh` still requires `alembic` in `src/backend/.venv` to apply schema migrations:
- Install once: `src/backend/.venv/bin/pip install alembic`
- Then rerun backend startup script.
