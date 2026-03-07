# C2C Detail Snapshot Migration

## Goal

Replace read dependency on `c2c_price_history` with `c2c_items_details.snapshot_at`, while preserving historical timelines and enabling incremental updates.

## What Changed

1. `c2c_items_details` adds `snapshot_at` and index `idx_c2c_details_c2c_snapshot_at`.
2. `save_items` now appends detail snapshots (no delete-then-insert overwrite for history use-cases).
3. Historical timestamps are backfilled from `c2c_price_history.recorded_at` into `c2c_items_details.snapshot_at`.
4. Price-history API tests were updated to match snapshot-based semantics.
5. Backend runner now executes Alembic from `src/backend/.venv` and includes install guidance.

## Alembic Revisions

- `b8f9c7a12d34_add_snapshot_at_to_c2c_item_details.py`
- `c4d2e8a9f1b0_backfill_detail_snapshots_from_price_history.py`

`c4d2e8a9f1b0` copies each item's latest detail composition to every historical `recorded_at` point from `c2c_price_history`, with `NOT EXISTS` de-duplication.

## Deploy / Migrate

1. Ensure backend venv has Alembic:
   - `src/backend/.venv/bin/pip install -r src/backend/requirements.txt`
2. Run migrations:
   - `src/backend/.venv/bin/alembic upgrade head`
3. Start backend:
   - `./scripts/run-backend.sh`

## Verification

- Full backend tests:
  - `pytest -q src/backend/testsuite`
- Current result in this change set:
  - `159 passed`

## Notes

- After this migration path, `c2c_price_history` can remain as legacy data storage, but new historical reads should come from `c2c_items_details.snapshot_at`.
- If later removing `c2c_price_history`, do it in a separate migration after observing stable production behavior.
