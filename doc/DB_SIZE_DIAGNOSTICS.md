# Database Size Diagnostics

This document describes the database size diagnostics endpoint, CLI helper, and admin UI integration.

## API

- Endpoint: `GET /api/settings/db-size`
- Auth: admin only
- Query params:
  - `days` (optional, default `7`, range `1..3650`)
  - `top_n` (optional, default `20`, range `1..200`)

### Response fields

- `generated_at`: UTC time when the report is generated.
- `backend`: configured backend name (`sqlite` / `cloudflare` / etc).
- `dialect`: SQL dialect name (`sqlite`, `postgresql`, ...).
- `days_window`: effective recent-window days used for `recent_rows`.
- `table_count`: number of scanned user tables.
- `total_rows`: sum of `row_count` from scanned tables.
- `recent_total_rows`: sum of `recent_rows` (when available).
- `total_db_bytes`: full database file size (SQLite) or database size (PostgreSQL).
- `used_db_bytes`: SQLite used bytes (`(page_count - freelist_count) * page_size`).
- `free_db_bytes`: SQLite freelist bytes.
- `wal_bytes`: SQLite WAL file size.
- `tables_total_bytes`: sum of per-table total bytes.
- `skipped_tables`: tables skipped due to internal/system restrictions.
- `warnings`: non-fatal warnings (single-table failures).
- `tables`: top-N tables sorted by size desc.

Each table item includes:
- `name`
- `row_count`
- `recent_rows`
- `table_bytes`
- `index_bytes`
- `total_bytes`

## Recent rows logic

- Generic tables: use first available timestamp column in this order:
  - `updated_at`
  - `recorded_at`
  - `created_at`
- `c2c_items_snapshot` is special-cased:
  - `recent_rows` is calculated via join to `c2c_items` using:
  - `COALESCE(c2c_items.updated_at, c2c_items.created_at) >= cutoff`
  - This reflects snapshot growth tied to active listing updates.

## Cloudflare D1 notes

Cloudflare D1 may expose internal tables (for example `_cf_*`) that are not readable by normal SQL (`SQLITE_AUTH`), and may time out on full-table diagnostic scans.

Diagnostics behavior:
- Internal/system tables are skipped.
- Diagnostics use a lightweight mode to avoid timeout-prone queries.
- In lightweight mode, table/index byte fields are not estimated and are returned as `null`.

## Admin UI behavior

In `/admin/settings`:
- The diagnostics panel is placed **below system logs**.
- It does **not** auto-run on page load.
- Only manual trigger (`开始诊断` / `重新诊断`) requests diagnostics.

## CLI helper

- Script: `src/bsm-cli/db_size.py`
- Example:
  - `python3 src/bsm-cli/db_size.py --days 7 --top 20`
- If backend loading fails (for example missing D1 dialect plugin locally), the script prints a hint to run with `BSM_DB_BACKEND=sqlite`.
