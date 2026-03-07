# Changelog

## [0.9.3] — 2026-03-07

### Added

- **Product Triple Table**: Added new `product` table keyed by `(blindbox_id, items_id, sku_id)` for normalized product metadata (`name`, `img_url`, `market_price`).
- **Snapshot Table**: Added `c2c_items_snapshot` table to store per-listing component snapshots and proportional estimated prices over time.
- **BLOB Compression Migration Script**: Added `src/bsm-cli/migrate_product_snapshot.py` to backfill `detail_blob` and migrate legacy data into `product` and `c2c_items_snapshot`.
- **Migration Plan Doc**: Added `doc/C2C_PRODUCT_SNAPSHOT_BLOB_MIGRATION.md` documenting phased rollout, validation, and rollback.

### Changed

- **`c2c_items` Raw Detail Storage**: Added `detail_blob` + `detail_codec` (`gzip`) and switched runtime read path to prefer blob decode with JSON fallback.
- **Scan Save Path Dual-Write**: `save_items` now writes:
  - legacy `c2c_items_details`,
  - normalized `product`,
  - `c2c_items_snapshot` with proportional `est_price`,
  while keeping `detail_json` for compatibility.
- **Backfill Compatibility**: `src/backend/backfill_details.py` now supports blob-first detail parsing.

## [0.9.2] — 2026-03-06

### Added

- **Cron Monitor Heartbeat/Uptime Logs**: Added monitor heartbeat logs with `uptime`, `idle`, and monitor check interval output to improve runtime visibility in Cloudflare-only logging environments.
- **Frontend API Retry Layer**: Added a centralized retry mechanism in `src/frontend/src/lib/api.ts` with up to 3 attempts for transient failures (`timeout`, network error, `408/429/5xx`) using exponential backoff.

### Changed

- **Market Sorting Semantics**: `TIME_DESC` now maps to creation-time ordering (`created_at DESC`, fallback `updated_at`) instead of implicit ID order. Added explicit `ID_ASC` / `ID_DESC` support in backend market ordering paths.
- **Market UI Sort Options**: Updated market and listing sort labels to `创建时间(新-旧)` and added explicit ID sort options in `/market`, `/market/[id]`, and `/product/[id]`.
- **Next.js Prefetch Policy (Market)**: Disabled prefetch for all links in `/market` card list to reduce unsolicited XHR, while keeping `/market/[id]` page navigation links on default prefetch behavior.
- **Scan Sort Default Copy**: Synced scan sort default copy to `创建时间排序（TIME_DESC）` in `config.yaml.example` and admin settings UI.
- **Cloudflare Container Idle Timeout**: Updated `cf-worker/index.ts` container `sleepAfter` to `720h` for long idle retention.
- **Local CF Docker Runner Restart Policy**: `scripts/run-docker.sh` now defaults to Docker `--restart unless-stopped` (configurable via `RESTART_POLICY`), and README Cloudflare container instructions were updated accordingly.

### Tests

- Added DB regression assertions for `ID_ASC` / `ID_DESC` listing ordering and `TIME_DESC` creation-time ordering in `test_db.py`.
- Added market UI assertions for new sort options in `test_market_page_ui.py`.
- Added market prefetch policy assertions for `/market` and `/market/[id]` in UI tests.
- Added admin settings UI assertion for scan sort default copy in `test_dashboard_ui.py`.

## [0.9.1] — 2026-03-06

### Added

- **Admin Scan Summary Push Window Config**: Added `admin_scan_summary_interval_seconds` (default `600`) to runtime config and admin settings UI/API. Cron now sends periodic admin Telegram scan summaries using this configurable interval.
- **Category Sleep Backoff**: Added first-page repeat sleep backoff per category in scan loop. When a category hits repeat on page 1, it sleeps for `1 -> 2 -> 3 ...` rounds (max `6`) before scanning again.

### Changed

- **Multi-Category Scan Scheduling**: Enabled categories are no longer scanned round-robin one-per-cycle. Each cron cycle now scans all active categories in parallel.
- **Multi-Session Category Assignment**: When multiple Bili sessions are available, category scans are distributed to maximize concurrent usage while keeping category-to-session assignments sticky when possible.
- **Market Default Ordering**: Market list default ordering now follows `c2c_items_id DESC`.
- **Filter Semantics (`price_filters` / `discount_filters`)**: If all options are selected, settings now persist as an empty list (`[]`) to represent "no limit", and settings API reads `[]` back as "all selected" for UI display.
- **Market Search Button Behavior**: On `/market`, clicking search now triggers a refresh even when the keyword is unchanged.

### Fixed

- **Settings Save Reliability**: Config persistence no longer silently swallows write failures; `/api/settings` now returns an explicit save error when persistence fails.

## [0.9.0] — 2026-03-04

### Added

- **Market Category Filter**: `/market` now supports a multi-select category filter (手办 / 模型 / 周边 / 3C / 福袋) backed by persisted `category_id` data in `c2c_items`, including router filtering support for both list and search endpoints.
- **First-Run Config Bootstrap**: On first startup, if neither project-root `.env` nor `config.yaml` exists, the app now auto-generates both from `.env.example` and `config.yaml.example`.

### Changed

- **Market Filter UX**: Replaced the old mix of native `select` inputs and exposed category checkboxes with unified in-page dropdown menus for 时间 / 排序 / 分类. Category selections are now applied only when the dropdown closes, making multi-select changes less noisy.
- **Price Discount Display**: Added compact `X.X折` labels beside prices on the market list, the market detail header, and recent listing rows.
- **Shared App Footer**: The login page and in-app pages now render the same footer content, showing `v0.9.0 | © Touko Hoshino` from a shared frontend component.
- **Admin Settings Polling Guard**: `/admin/settings` no longer starts polling cron status and logs before the page finishes its initial settings load, preventing a burst of early requests while the page is still bootstrapping.
- **Scan Controls and Scheduling**: Added admin-only `立即扫描` and `重启 Cron` controls in system settings, simplified scan logs, enforced a 30-second scan timeout, made scan-interval saves restart cron immediately, and reset scan progress to page 1 on cron restart.
- **Category-Aware Scan Rotation**: Multi-category scan mode now rotates categories one at a time with independent cursor state. `CUR` now caps at 30 pages per category.
- **Test Suite Layout**: Python regression tests were moved from the root `tests/` folder to `src/backend/testsuite`, with `scripts/run-tests.sh` and `scripts/run-lint.sh` added as the standard local verification entry points.

### Fixed

- **Cloudflare D1 Log Noise**: `/api/settings/logs` polling no longer emits repetitive `[CF D1]` request timing lines, while cron logs continue to print to the backend logger.
- **Database Connection Simplicity**: Removed explicit SQLAlchemy `pool_size` configuration and the unused `db_pool_size` runtime setting, simplifying database engine creation and config surface.

## [0.8.10] — 2026-03-04

### Added

- **Cloudflare Login Validation**: Added runtime-configurable Cloudflare Turnstile protection for login. Admins can now enable/disable verification from system settings and configure `Turnstile Site Key` / `Turnstile Secret Key`. The login page reads a new public login-settings endpoint and renders Turnstile only when enabled.
- **Admin Telegram Alert Targets**: Added `Admin Telegram IDs` as a system setting. Multiple TG IDs are supported and used for system alerts.
- **Cloudflare Login Test Coverage**: Added regression tests covering missing Turnstile token, empty token, invalid token, valid token, public login settings exposure, and login page wiring.

### Fixed

- **Notification Center Layout**: Reworked `/notifications` so `监听关键词` and `Telegram ID` stay as the editable config area, while `Telegram 绑定` and `测试推送` are separated into lower action sections. Mobile spacing and the market auto-refresh button wrapping were also adjusted.
- **Telegram Push Links**: Telegram item notifications now include the application detail-page link (using the configured app base URL) in addition to the Bilibili source link.
- **System Alerting + Fail2Ban**: Added in-app Fail2Ban-style login throttling keyed by client IP (now honoring `CF-Connecting-IP`, `X-Forwarded-For`, and `X-Real-IP`). The policy is now 5 failed attempts within 5 minutes, followed by a 15-minute ban. Scan `429` (too frequent) and scan-loop exceptions now also notify configured admin Telegram IDs.

## [0.8.9] — 2026-03-03

### Fixed

- **Scan Mode Semantics**: `latest` now consistently means "always scan the latest page", while `continue` now advances with an in-memory `nextId` cursor inside the running process, resets to page 1 after restart, and caps each pass at 50 pages. Added `continue_until_repeat` for the stricter variant that resets to page 1 on the next cycle as soon as a scanned page contains any already-known item.
- **Runtime Filter Loading**: `price_filters`, `discount_filters`, and `sort_type` are now loaded from runtime config instead of silently falling back to hardcoded defaults.
- **New-Item Notifications Only**: scan notifications now trigger only for items that are newly inserted during the current scan cycle, preventing repeated alerts for older items that are still present on the latest page.
- **Account Ordering**: account management lists now return users in descending creation order so newly created accounts appear first.

### Added

- **Dashboard Scan Metrics**: the user homepage now shows `今日刷新次数`, `今日新增商品`, and a clickable `数据库延迟` probe that can re-run a DB latency test inline.
- **Homepage Refresh Action**: the user homepage now includes a bottom `刷新首页数据` button that refreshes both dashboard stats and DB latency in one action, while keeping the existing responsive button sizing.
- **Scan Mode UX Copy**: the admin settings page now explains `latest` and `continue` behavior via hover text, including the `continue` 50-page cap and restart reset behavior.
- **Regression Coverage**: added and expanded tests for runtime filter loading, `continue` cursor behavior, new-item filtering, account DB ping, homepage dashboard payloads, and account ordering.

## [0.8.8] — 2026-03-03

### Fixed

- **Notification Center Mobile Layout**: The `/notifications` settings form now collapses cleanly on narrow screens. Two-column setting rows stack vertically on mobile, action rows no longer leave an empty spacer column, and long bind/test status text can wrap instead of blowing out the card width.
- **Keyword-Free Test Push**: `POST /api/settings/user-notifications/test` no longer rejects empty keyword lists. Test pushes now always send a timestamped message using the configured runtime timezone, and still append the current keyword list when keywords exist.
- **Telegram Binding Refresh Sync**: Clicking `同步/刷新机器人` in `/notifications` now polls the latest user notification config up to 6 times at 1-second intervals and immediately rewrites the `Telegram ID` textarea when a new bound chat ID appears, instead of often showing stale data from a too-early single refetch.

## [0.8.7] — 2026-03-03

### Added

- **BiliSession Selection Strategy Config**: Added runtime-configurable `bili_session_pick_mode` with `round_robin` (least recently used) and `random` strategies, exposed through `GET/PUT /api/settings` and the admin settings page.
- **BiliSession Failure Cooldown**: Added `bili_session_cooldown_seconds` (default `60`) so sessions marked with an error are temporarily skipped instead of being retried immediately. A value of `0` disables cooldown.

### Fixed

- **Session Reuse After Failure**: `load_next_bili_session()` and `has_active_bili_session()` now both respect recent session failures, preventing a broken Bili session from being selected repeatedly during the cooldown window.

## [0.8.6] — 2026-03-03

### Performance

- **Request Concurrency Fix**: Converted synchronous DB-backed read endpoints in `src/backend/routers/market.py` and `src/backend/routers/settings.py` from `async def` to standard `def` so FastAPI runs them in its threadpool instead of blocking the event loop. This removes cross-request queueing where unrelated API calls were all stalling to roughly the same latency.
- **Config Response Cache**: Added a 5-minute in-memory cache for `GET /api/account/settings`. The cached payload is invalidated explicitly when `PUT /api/settings` updates runtime settings, reducing repeated config loads on the market homepage.
- **Market Price History Query Merge**: `GET /api/market/items/{id}/price-history` now uses a single DB query to resolve `items_id` and load either aggregate product history or direct item history in one pass.
- **Cloudflare D1 Instrumentation**: Added per-request D1 query count and cumulative timing logs when `BSM_DB_BACKEND=cloudflare` to make remote latency visible during debugging.

### Fixed

- **Graceful Shutdown Delay**: `Ctrl+C` shutdown no longer hangs behind Telegram long-polling as aggressively. Blocking bot operations were moved off the event loop with `asyncio.to_thread(...)`, and FastAPI lifespan shutdown now cancels and awaits both the cron and Telegram background tasks.
- **Market Bundle Card Navigation**: On `/market`, bundled image tiles inside multi-item cards no longer hijack clicks to child product pages. The entire card now consistently navigates to the main market item detail page, and bundled thumbnails share the same hover feedback as single-image cards.
- **Optional YAML Dependency**: Missing `PyYAML` no longer crashes Alembic or lightweight environments. YAML-backed config loading now falls back cleanly when the dependency is absent.

## [0.8.5] — 2026-03-03

### Performance

- **Auth User Caching**: Added 600s TTL in-memory cache for `get_access_user()`. Every API request previously triggered a DB round-trip for authentication, costing ~100-300ms on Cloudflare D1. Cache is automatically invalidated when users are modified or deleted.
- **Market Items Query Simplification**: Replaced the expensive per-row correlated subquery (`_market_recent_listing_count_expr`) in `_load_market_items_page` with a separate batch fetch via `get_15d_listing_counts_batch()`. This splits 1 complex query into 2 simpler queries that execute significantly faster on D1.
- **Missing Index**: Added `idx_c2c_price_history_c2c_items_id` index on `c2c_price_history.c2c_items_id` to speed up price history lookups.

### Added

- `tests/test_perf_optimizations.py` — 9 test cases covering auth user cache behavior (TTL, invalidation on mutation, reset) and batch listing count correctness.

---

## [0.8.4] — 2026-03-03

### Fixed

- **Account Update Logic**: Refactored user upsert into separate Create (`POST`) and Update (`PUT`). This fixes the issue where renaming a user created a new account instead of modifying the existing one.
- **Empty Password Handling**: Admins can now explicitly create or modify users with an empty password string (signifying "no change" during edits) without triggering 422 validation errors.
- **Broken Test Cases**: Fixed regression in `test_accounts_router.py` where duplicate username checks were not being correctly Asserted.

### Added

- **User-Level Settings API**: Added `GET /api/account/settings` accessible to regular users, allowing access to market refresh intervals without admin privileges.
- **Header User Dropdown**: Implemented a new premium dropdown menu in the app header. The user role and logout button are now tucked away inside a menu triggered by clicking the username, improving UI cleanliness and reducing visual noise.
- **Market Pagination Tuning**: Increased default items per page from 12 to **20** on both backend and frontend to optimize browsing experience.

### UI/UX

- **Danger Buttons**: Styled the "Delete User" button in the account management panel as red (`bsm-btn-danger`) as per design request.
- **Dropdown Animations**: Added glassmorphism backdrop filters and subtle translateY animations for the new header menu.

---

## [0.8.3] — 2026-03-03

### Fixed

- **Listing Disappearance on Refresh**: Fixed an issue where items would disappear from the "Recent 15-day listings" view after being refreshed. Introduced a dual-timestamp system (`created_at` for original discovery time, `updated_at` for last activity) to ensure items remain visible for 15 days from their last active scan, while still displaying their original listing time.
- **Migration Idempotency**: Fixed a Cloudflare D1 migration error caused by setting non-constant `server_default` values in `ALTER TABLE ADD COLUMN`. 

### Added

- **Parallel Batch Refresh**: Introduced a new backend endpoint (`POST /api/market/items/batch-refresh`) that accepts an array of item IDs and refreshes their statuses concurrently (capped at 10 items per request, using 5 parallel workers).
- **Progressive UI Updates**: Refactored the "一键刷新当页状态" button on the Market Detail page. Instead of blocking the UI until all items finish, it now fires concurrent batch XHR requests and progressively updates individual listing tags in real-time as each batch returns.
- **Refresh Shimmer Animation**: Added a visual shimmer loading animation to explicitly indicate which specific listing rows are currently in-flight during a batch refresh without blocking the rest of the list.

## [0.8.2] — 2026-03-02

### Fixed

- **Global 401 Redirects**: All frontend pages (Market, Dashboard, Notifications, Settings) now correctly intercept 401 Unauthorized responses from the backend, clearing local session data and redirecting to the login page after a 5-second toast notification.
- **Login UI Cleanup**: Removed pre-filled test credentials and account hints from the login page for a cleaner production interface.
- **Log Auto-Scroll**: Refactored the `/admin/settings` system log window to use `scrollTop` instead of `scrollIntoView`, preventing the browser from shifting focus or jumping the page when new logs arrive.
- **API Client Consistency**: Fixed `apiDelete` in `src/lib/api.ts` to properly pass context to the response handler. Removed redundant `fetch` calls across the app in favor of the centralized `apiGet`/`apiPost` helpers.

### Added

- **Product Aggregation View (`/product/[id]`)**: Built a dedicated metadata dashboard for distinct Bilibili `items_id` components. The product overview aggregates min/max price ranges from all encompassing C2C market arrays over 15-days. Bundled package images on the `/market` dashboard now behave as functional shortcut links routed to their absolute `/product` view. 
- **Product API Navigation**: Built new SQL backend aggregation functions translating user clicks on distinct figures into macro-level `/api/market/product/{id}*` requests that retrieve 15D historical scopes and related item groupings independent of bundle configurations.
- **Market Item Bundles**: `GET /api/market/items/{id}/recent-listings` now parses and returns `bundled_items` from the raw item's `detailDtoList`. The frontend now intelligently renders bundles up to 9-grid cards for complex multi-item listings.
- **Image Zoom Overlay**: Added a lightweight, purely React-driven lightbox to enlarge both main product images and individual packaged bundled items on the Market Details page.
- **HPoi Search Shortcuts**: Added direct HPoi index query buttons for each bundled sub-item, automatically striping out the trailing "等X个商品" text.
- **Responsive Stats Layout**: The "Recent 15-day listings" statistics box auto-reorders using CSS structural `order` flex fields on Mobile to sit appropriately above the Scatter price charts to optimize vertical screen real estate.
- **Responsive Chart Layout**: The Price History ScatterChart dynamically snaps into the `main-content` left column structure alongside bundled items in desktop views (and below them on Mobile viewing). Unbundled items let the chart span full fluid width.
- **Decoupled API Chart Loading**: Separated the single detail API lookup into independent concurrent loads for Header Metadata and Price Charts. The chart now has its own unique 100% viewpoint width DOM structure decoupled from the parent CSS grid.
- **Structural Loading Skeletons**: Developed an accurate CSS mirrored loading skeleton layout on the Market Detail header and `Shell` title that paints a responsive, multi-line gray representation of the DOM immediately upon navigation while data fetches.

### Security

- **Backend Auth Enforcement**: Configured `HTTPBasic` with `auto_error=False` to prevent the browser's native Basic Auth prompt. Standardized 401 JSON responses across all routers for better frontend error handling.
- **Role-based Access**: Verified that all sensitive endpoints (Admin settings, Account management) strictly enforce `admin` role requirements.

---

## [0.8.1] — 2026-03-02

### Fixed

- **Negative timestamp display** (`-16248 秒前`): `_now()` in `src/bsm/db.py` was storing local time (`Asia/Shanghai`) without timezone info. The frontend `timeAgo()` function mistakenly appended `Z`, treating it as UTC, causing an 8-hour (28800 s) future offset and negative diffs.
  - `src/bsm/db.py` — `_now()` now returns UTC with `Z` suffix (`2026-03-02T11:30:00Z`).
  - `src/frontend/src/app/market/page.tsx`, `market/[id]/page.tsx`, `admin/settings/page.tsx` — Removed forced `Z` appending; naive timestamps are now parsed as local time by the browser. Added `diff < 0` guard (displays `刚刚`) for any residual clock skew.

### Added

- **Database Connection Monitor**: Added a new settings endpoint (`GET /api/settings/db-ping`) and UI component on the `/admin/settings` page to view and test real-time SQLite/Cloudflare D1 database latency.
- **Notification Center Settings**: `/notifications` is now a real user-facing notification settings page. Each user can configure multiple listener keywords, multiple Telegram IDs, a per-user enable/disable switch, and send a Telegram test push for the current keywords.
- **User Notification Test API**: Added `POST /api/settings/user-notifications/test` to send a test message containing the current keyword list to the current user's configured Telegram IDs.
- **Admin System Log Panel**: The scan log viewer was moved into `/admin/settings` and placed at the bottom of the page as a system log panel.

### Changed

- **User notification storage model**: User notification settings (`keywords`, `telegram_ids`, `notify_enabled`) now live in the `access_users` database table. Legacy `config.yaml` user entries are only used as one-time import fallback when the database is empty.
- **Removed global keyword source**: `BSM_PARSE` and the corresponding system settings field, Telegram `/setquery` command, and global notify matching path were removed. Notifications now only use per-user keywords from the database.
- **Removed global Telegram targets**: Global Telegram config fields (`chat_ids`, `admin_chat_ids`, `heartbeat_chat_ids`, `chat_rules_json`) were completely removed from `config.yaml` and backend scripts. `telegrambot.py` and `notify.py` now exclusively rely on per-user `telegram_ids` settings from the database for message delivery and admin authorization.
- **Admin navigation consolidation**: The standalone `管理后台` nav entry was merged into `系统设置`; `/admin` now redirects to `/admin/settings`.
- **User navigation consolidation**: The standalone `我的规则` nav entry was merged into `通知中心`; `/rules` now redirects to `/notifications`.
- **Account page consolidation**: `/account` is now the unified account page. "我的账户" stays at the top, and the admin-only "账户管理" module is rendered below it on the same page. The standalone admin nav entry was removed, and `/admin/users` now redirects to `/account`.
- **Targeted Telegram delivery**: `src/bsm/notify.py` now sends only per-user targeted Telegram alerts based on each user's keywords and skips delivery when that user's notification switch is disabled.
- **Test suite cleanup**: Deleted obsolete Reflex UI test files (`test_bili_sessions.py`, `test_ui_language.py`, `test_web_auth.py`, `test_web_navigation.py`, `test_bili_qr_login.py`, `test_login_defaults.py`, `test_run_script.py`, `test_transport_config.py`) as the UI is now exclusively Next.js. Fixed `test_db.py` to properly mock Alembic's target SQLite database environment natively.

---

## [0.8.0] — 2026-03-02

### Changed (Breaking)

- **Removed Reflex** completely. The `bsm_reflex/` package, `rxconfig.py`, `reflex.db`, `.states/`, and `.web/` are gone.
- **Backend** is now a standalone **FastAPI** application in `src/backend/`, managed by its own pyvenv (`src/backend/.venv`).
- **Frontend** is now a standalone **Next.js 15** application in `src/frontend/`, managed by **pnpm**.
- `scripts/run.sh` now deprecated/split into `scripts/run-backend.sh` and `scripts/run-frontend.sh` using `exec` to fix stale PID port collisions.
- Root `requirements.txt` no longer lists `reflex`.

### Added

- `src/backend/main.py` — FastAPI app entry with CORS and router registration.
- `src/backend/auth.py` — Authentication against `access_users` via `src/bsm/db` (later evolved from client-stored auth to cookie-backed session auth).
- `src/backend/backend.py` — Bili session / QR helpers using `src/bsm/db` and `src/bsm/api`.
- `src/backend/routers/auth.py` — `POST /api/auth/login`, `POST /api/auth/logout`, `WS /api/ws/auth`.
- `src/backend/routers/sessions.py` — `GET /api/admin/sessions`, `DELETE /api/admin/sessions/{u}`, `WS /api/ws/admin/sessions`.
- `src/backend/routers/qr.py` — `GET /api/admin/qr/create`, `POST /api/admin/qr/poll`, `WS /api/ws/admin/qr`.
- `src/backend/routers/market.py` — `GET /api/market/items`, search, price-history, and paginated recent-listings.
- `src/backend/routers/settings.py` — `GET /api/settings`, `PUT /api/settings`, `GET /api/settings/cron`, `GET /api/settings/logs`.
- `src/backend/cron_runner.py` / `cron_state.py` — Natively integrated backend scan loop in FastAPI `lifespan` with in-memory log buffer.
- `src/frontend/next.config.ts` — `/api/*` rewrite proxy to FastAPI.
- `src/frontend/src/lib/api.ts` — Dual-stack API client (`apiGet`, `apiPost`, `apiDelete`, `BsmWsChannel`).
- `src/frontend/src/contexts/AuthContext.tsx` — frontend auth context (initially localStorage-based, later migrated to cookie-backed session restore).
- `src/frontend/src/components/Shell.tsx` — App shell with sticky nav, role badge, logout button.
- `src/frontend/src/app/globals.css` — Premium dark glassmorphism CSS design system.
- 12 page components under `src/frontend/src/app/` covering all existing Reflex routes + new Market list/detail pages.
- **Market Detail Page UI Refinements**: 
  - Scatter chart replacing line chart for historical prices to show all price points, including item names and bundled indicators.
  - Server-side and client-side pagination for 15-day listings (20 items per page).
- **Database Optimizations**: Explicit indices (`items_id`, `updated_at`, `c2c_items_id`) and optimized subqueries to fix slow D1 SQLite execution plans for `recent_listings`.
- **Config Migration**: Mutable application configurations (`BSM_SCAN_MODE`, `interval`, `parse`, Telegram keywords, Notification settings, etc) were migrated out of `.env` entirely into project-root `config.yaml` to allow real-time runtime editing and reduce `.env` clutter.
- **User Management Migration**: User management was moved to database-backed `access_users`, with runtime editing exposed through the admin UI.
- **Timezone Configuration**: Added configurable `timezone` (default `Asia/Shanghai`) to `config.yaml`. Backend `cron_state.py` and `db.py` now parse standard local time correctly via `zoneinfo` over `CURRENT_TIMESTAMP`/`utcnow`. Frontend parsing rules were adjusted to prevent duplicate `Z` UTC suffixes.

### Preserved

- All `src/bsm/` business logic (DB, API, scan, notify, Telegram) — **zero changes**.
- All XHR and WebSocket API routes at the same paths.
- Existing login and route structure while later auth persistence evolved to cookie-backed sessions.
- Dual-stack WebSocket endpoints for all three domains (auth, sessions, QR).
- `.env` configuration format and all existing env variables.
