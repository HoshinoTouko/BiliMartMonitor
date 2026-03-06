# Work Log

## 2026-03-06 Monitor Uptime Logs, Market Sorting Semantics, and Frontend API Retry

### Planned

- Improve runtime observability for Cloudflare container deployments where process state is inferred mostly from logs.
- Align market sorting behavior and labels so `TIME_DESC` follows creation-time ordering and expose explicit ID ordering.
- Add frontend retry guardrails to reduce single-request failures from transient network and upstream issues.
- Keep deployment docs/scripts aligned with long-running container expectations.

### Step Log

1. Extended monitor behavior in `src/backend/main.py` to emit periodic monitor heartbeat lines containing `uptime`, `idle`, and effective check interval (`interval * 12`), while preserving existing restart-on-inactivity logic.
2. Added retry orchestration to `src/frontend/src/lib/api.ts`:
   - max 3 attempts with exponential backoff,
   - retry only on transient classes (`timeout`, network error, `408/429/5xx`),
   - idempotent methods (`GET/PUT/DELETE`) enabled, `POST` kept single-attempt to avoid duplicate side effects.
3. Updated backend DB ordering in `src/bsm/db.py`:
   - `TIME_DESC/TIME_ASC` now map to `created_at` ordering (fallback to `updated_at` for legacy rows),
   - added explicit `ID_ASC/ID_DESC` branches for market and recent-listing queries.
4. Updated frontend sort copy/options in market pages to expose `创建时间(新-旧)` and explicit ID sorting choices.
5. Synced scan-sort default copy across docs/UI (`config.yaml.example`, admin settings page) to `创建时间排序（TIME_DESC，默认）`.
6. Updated Cloudflare container timeout to `sleepAfter = "720h"` in `cf-worker/index.ts`.
7. Updated `scripts/run-docker.sh` to default to `--restart unless-stopped` with `RESTART_POLICY` override support; documented usage in `README.md`.
8. Added/updated regression tests for market sort options, ID ordering behavior, and creation-time TIME sorting behavior.
9. Tuned Next.js prefetch strategy:
   - disabled prefetch on `/market` list card links to reduce non-click XHR noise,
   - kept `/market/[id]` page links on default prefetch behavior.

### Verification

- `pytest -q src/backend/testsuite/test_db.py src/backend/testsuite/test_market_page_ui.py src/backend/testsuite/test_dashboard_ui.py`
- `pytest -q src/backend/testsuite/test_market_detail_page_ui.py`
- `pytest -q src/backend/testsuite/test_settings_router.py src/backend/testsuite/test_cron_runner.py`
- `pnpm -C src/frontend -s exec tsc --noEmit`

## 2026-03-06 Parallel Category Scan, Session Affinity, and Admin Summary Enhancements

### Planned

- Remove one-category-per-round polling for multi-category scans.
- Utilize multiple Bili sessions concurrently while keeping category/session affinity stable.
- Add periodic admin Telegram scan summary with configurable interval.
- Reduce shallow-page churn by adding a category sleep backoff when page 1 repeats are detected.
- Align market/filter UX defaults and persistence behavior with real-world ops usage.

### Step Log

1. Reworked `src/backend/cron_runner.py` to scan all active categories in a single cycle and execute category scans in parallel.
2. Added category-to-session sticky assignment so categories prefer the same `login_username` across rounds while still spreading load across available sessions.
3. Added runtime-configurable admin summary push cadence (`admin_scan_summary_interval_seconds`, default `600`) across config loading, settings API, and admin settings UI.
4. Implemented per-category sleep backoff: when page 1 includes repeat items, the category enters sleep rounds with incremental backoff `1 -> 2 -> 3 ...` capped at `6`.
5. Added and expanded cron regression tests for summary formatting, category sleep backoff progression/cap, and new multi-category scan behavior.
6. Updated settings and market behavior:
   - `price_filters` / `discount_filters` full-selection now persists as `[]` (unlimited semantics), with response normalization back to "all selected".
   - market default order now uses `c2c_items_id desc`.
   - `/market` search button now refreshes even when query text is unchanged.
7. Improved settings persistence error handling so failed config writes are surfaced via API errors instead of silently passing.
8. Synced `config.yaml.example` comments with current scan behavior (parallel multi-category + first-page repeat sleep backoff).

### Verification

- `pytest -q src/backend/testsuite/test_cron_runner.py`
- `pytest -q src/backend/testsuite/test_settings_router.py`
- `pytest -q src/backend/testsuite/test_market_router.py`
- `pytest -q src/backend/testsuite/test_market_api.py`

## 2026-03-04 Scan Controls, Category Rotation, and Market Filter UX

### Planned

- Add safer admin controls for cron execution and restart.
- Simplify scan logging and tighten scan timeout behavior.
- Make multi-category scanning rotate one category at a time with independent progress.
- Add market-side category filtering with cleaner dropdown UX and inline discount visibility.
- Reduce noisy admin-settings polling during page bootstrap.

### Step Log

1. Simplified scan log messages in `src/backend/cron_runner.py`, added a 30-second scan timeout, and wired manual trigger / cron restart controls into the admin settings API and UI.
2. Refactored cron restart handling in `src/backend/main.py` so restarting the cron task also resets in-memory scan progress, causing `CUR` to restart from page 1 immediately.
3. Reworked scan state to track cursor and page progress per category, then changed multi-category scans to rotate categories round-robin instead of merging all selected categories into one request. `CUR` now caps at 30 pages.
4. Added category label mapping in cron logs so scan logs print human-readable labels like `分类 手办` instead of raw category IDs.
5. Removed the explicit SQLAlchemy pool-size config and related docs/config entries, simplifying DB engine initialization.
6. Added `category_id` persistence to `c2c_items`, including a migration and runtime schema compatibility fallback, then exposed category filters on `/api/market/items` and `/api/market/items/search`.
7. Added a multi-select market category filter to the frontend and then refactored all market filters (时间 / 排序 / 分类) into a consistent custom dropdown UI. Category changes now apply only when the dropdown closes.
8. Added inline discount text (`X.X折`) beside prices in the market list, market detail header, and recent listing rows.
9. Changed `/admin/settings` polling so cron/log polling waits until initial page settings are loaded, preventing excessive early requests.
10. Added and updated route/UI tests for cron behavior, settings actions, market category filtering, market filter UI, and market detail discount rendering.

### Verification

- `python3 -m unittest tests.test_cron_runner tests.test_settings_router`
- `python3 -m unittest tests.test_market_router tests.test_market_page_ui tests.test_market_detail_page_ui`
- `python3 -m unittest tests.test_dashboard_ui`

## 2026-03-04 Cloudflare Login Validation, Admin Alerts, and Notification UX Cleanup

### Planned

- Add an optional Cloudflare verification gate to login.
- Add admin Telegram recipients for system-level alerts.
- Tighten the in-app Fail2Ban window and make it proxy-aware.
- Clean up the notification center mobile/desktop layout.

### Step Log

1. Extended runtime config loading and `/api/settings` read/write support with `app_base_url`, `admin_telegram_ids`, `cloudflare_validation_enabled`, and Turnstile site/secret keys.
2. Added `/api/public/login-settings` so the login page can safely fetch the Cloudflare login gate settings without requiring authentication.
3. Updated the login page and auth context to load public login settings, render Cloudflare Turnstile only when enabled, and submit `cf_token` with login requests.
4. Added backend Turnstile verification in the login route. Missing, empty, or invalid tokens are rejected before credential checks when Cloudflare validation is enabled.
5. Added admin Telegram alert delivery helpers and wired system alerts for scan `429`, scan loop exceptions, and Fail2Ban-triggered login abuse events.
6. Updated the in-app Fail2Ban logic to use forwarded client IP headers (`CF-Connecting-IP`, `X-Forwarded-For`, `X-Real-IP`) and changed the policy to 5 failed attempts in 5 minutes with a 15-minute ban.
7. Reworked `/notifications` layout so editable settings and action sections are visually separated, cleaned up mobile spacing, and adjusted the `/market` auto-refresh control so it no longer wraps awkwardly on small screens.
8. Added and updated tests for auth enforcement, Cloudflare login validation, settings persistence, login page UI wiring, and notification page UI expectations.

### Verification

- `python3 -m pytest tests/test_settings_router.py tests/test_auth_enforcement.py tests/test_notifications_page_ui.py tests/test_login_page_ui.py`
- `python3 -m py_compile src/backend/auth.py src/backend/routers/auth.py src/backend/routers/settings.py src/backend/cron_runner.py src/bsm/settings.py src/bsm/notify.py src/bsm/scan.py`

## 2026-03-03 BiliSession Rotation Strategy and Cooldown

### Planned

- Make Bili session selection strategy configurable from system settings.
- Support both deterministic rotation and random session picks.
- Prevent a failed Bili session from being selected again immediately.
- Cover the new config and cooldown behavior with regression tests.

### Step Log

1. Extended `src/bsm/settings.py` runtime config loading with `bili_session_pick_mode` and `bili_session_cooldown_seconds`, including normalization and sane defaults.
2. Updated `src/bsm/db.py` so `load_next_bili_session()` chooses active sessions according to the configured strategy and skips recently failed sessions until the cooldown expires.
3. Aligned `has_active_bili_session()` with the same availability filter so "has session" checks no longer report sessions that are still cooling down.
4. Exposed both settings through `src/backend/routers/settings.py` for read/write access from the admin settings API.
5. Added form controls to `src/frontend/src/app/admin/settings/page.tsx` so admins can choose `round_robin` vs `random` and configure cooldown seconds directly in the UI.
6. Updated `config.yaml.example` to document the new keys and defaults.
7. Added test coverage for runtime config parsing, cooldown-based session skipping, settings API persistence, and validation errors for invalid mode / negative cooldown.

### Verification

- `python3 -m unittest tests.test_db tests.test_settings_router`

## 2026-03-03 Market Performance, Caching, and Shutdown Cleanup

### Planned

- Reduce repeated Cloudflare D1 latency on market page loads.
- Instrument D1 request count/timing per API request.
- Improve backend responsiveness under concurrent requests.
- Fix slow shutdown on `Ctrl+C`.
- Normalize multi-item market card click behavior.

### Step Log

1. Increased `/market` frontend page fetch size and loading skeletons to 20 items to match the backend default.
2. Reworked market list/search/detail SQL paths in `src/bsm/db.py` to collapse multiple serial lookups into consolidated queries where practical, including single-query market item price history resolution.
3. Added request-scoped Cloudflare D1 timing/count instrumentation in `src/bsm/db.py` and `src/backend/main.py` for debugging remote query latency.
5. Added a 5-minute in-memory cache for `get_public_account_settings()` and explicit cache reset after `PUT /api/settings`.
6. Converted synchronous read-heavy API handlers in `src/backend/routers/market.py` and `src/backend/routers/settings.py` from `async def` to `def` so FastAPI dispatches them via the threadpool instead of blocking the event loop.
7. Fixed shutdown behavior by cancelling both background tasks in `src/backend/main.py` and moving Telegram bot blocking work (`requests`, DB lookups, message sends) to `asyncio.to_thread(...)`.
8. Removed nested bundle-image navigation from `/market` cards so multi-item cards behave the same as single-item cards: the entire card routes to the main market detail view.
9. Added test coverage for public account settings cache behavior and config-driven DB pool size parsing.

### Verification

- `pytest tests/test_market_router.py tests/test_settings_router.py tests/test_market_api.py`
- `pytest tests/test_db.py tests/test_settings_config_path.py`
- `python3 -m py_compile src/backend/main.py src/backend/routers/market.py src/backend/routers/settings.py src/bsm/db.py src/bsm/settings.py src/bsm/telegrambot.py`

## 2026-03-02 Reflex → FastAPI + Next.js Migration

### Planned

- Remove Reflex entirely from the project.
- Replace with a proper two-tier stack: FastAPI (backend) + Next.js (frontend).
- Preserve all existing business logic in `src/bsm/` unchanged.
- Maintain all existing API contracts (same routes, same dual-stack XHR/WS support).
- Improve frontend UI with a premium dark glassmorphism design.

### Assumptions

- At the time of this migration step, auth was assumed to remain stateless on the server side; this was later replaced by `HttpOnly` cookie-backed sessions.
- The existing `src/bsm/db.py` SQLAlchemy backend is reused without modification.
- WebSocket endpoints from the old Reflex app are preserved 1:1 on the FastAPI side.
- The Next.js dev proxy (`/api/*` → `localhost:8000`) is sufficient for local development; production routing is a separate concern.
- Tests that import `bsm_reflex.*` will break and should be cleaned up in a follow-up.

### Step Log

1. Read all existing Reflex files: `bsm_reflex/{app,pages,state,components,backend,auth,models,navigation,orm_config,transport_config}.py`.
2. Created `src/backend/` package with `requirements.txt` (FastAPI, uvicorn, python-dotenv, sqlalchemy, qrcode, websockets).
3. Created `src/backend/auth.py`: `authenticate_credentials` and `ensure_default_access_users` using `src/bsm/db` directly (no Reflex session).
4. Created `src/backend/backend.py`: `list_bili_sessions`, `logout_bili_session`, `create_bili_login_qr`, `complete_bili_login_qr` using `src/bsm/db` and `src/bsm/api`.
5. Created `src/backend/routers/auth.py`: `POST /api/auth/login`, `POST /api/auth/logout`, `WS /api/ws/auth`.
6. Created `src/backend/routers/sessions.py`: `GET /api/admin/sessions`, `DELETE /api/admin/sessions/{username}`, `WS /api/ws/admin/sessions`.
7. Created `src/backend/routers/qr.py`: `GET /api/admin/qr/create`, `POST /api/admin/qr/poll`, `WS /api/ws/admin/qr`.
8. Created `src/backend/main.py`: FastAPI app with CORS for `localhost:3000`, router mounts, startup seed.
9. Created `src/backend/.venv` via `python3 -m venv` and installed all dependencies.
10. Verified all backend imports and app instantiation pass without errors.
11. Scaffolded Next.js 15 frontend with pnpm into `src/frontend/` (App Router, TypeScript, Tailwind).
12. Created `src/frontend/next.config.ts` with `/api/*` rewrite proxy to `localhost:8000`.
13. Created `src/frontend/src/lib/api.ts`: dual-stack API client (`apiGet`, `apiPost`, `apiDelete`, `BsmWsChannel`).
14. Created `src/frontend/src/contexts/AuthContext.tsx`: initial auth context matching the then-current frontend conventions (later migrated to cookie-backed session restore).
15. Created `src/frontend/src/components/Shell.tsx`: app shell with sticky header, role badge, nav bar, content area.
16. Created `src/frontend/src/app/globals.css`: full premium dark glassmorphism design system (CSS variables, animations, components).
17. Created all 10 page components: login (`/`), user dashboard (`/app`), market (`/market`), rules (`/rules`), notifications (`/notifications`), account (`/account`), admin dashboard (`/admin`), sessions (`/admin/sessions`), users (`/admin/users`), settings (`/admin/settings`).
18. Session management page includes the full QR login flow (generate → display QR image → poll → show result → refresh session list).
19. Deleted `bsm_reflex/`, `rxconfig.py`, `reflex.db`, `.states/`, `.web/`, `__pycache__/`.
20. Updated `scripts/run.sh` to start uvicorn (backend) and pnpm dev (frontend) in parallel with graceful shutdown.
21. Updated root `requirements.txt` to remove `reflex`.
22. Updated `.gitignore` to add `src/frontend/.next/`, `src/frontend/node_modules/`, `src/backend/.venv/`.
23. Implemented backend `market.py` API endpoints for listing items, searching, and price history with Next.js frontend rendering cards and recharts graphs.
24. Handled B站 CDN 403 blocks for images by adding `referrerpolicy="no-referrer"` to React `<img>` tags.
25. Fully integrated Bilibili scanner `src/bsm-cli/cron.py` functionality natively into FastAPI using `lifespan` asyncio executor, replacing external script requirement.
26. Added `cron_state.py` containing an in-memory 200-line ring buffer for scanning logs and job status tracking.
27. Reworked market UI for viewing detailed item lists using single point records. Converted line charts to individual scatter charts based on unit price proportions, complete with real-time UI mapping properties like packaging flags.
28. Implemented seamless paginated scrolling on lists containing 15-day histories on client & server level.
29. Added missing SQLite indices globally (`idx_c2c_details_items_id`, `idx_c2c_items_updated_at`, etc) and rewrote D1 queries with forced subselect mapping. Query parsing speed improved from >5000ms loop-halt queries back down to milliseconds.
30. Designed realtime `admin/settings` frontend page to edit runtime settings, display live background job status, and read logs to Notification Center using `/api/settings/logs`.
31. Fixed stale process port binding crashes by refactoring `scripts/run.sh` into `scripts/run-backend.sh` and `scripts/run-frontend.sh` with active port-killing logic.
32. Updated `doc/ARCH.md` and `doc/WORKLOG.md` to reflect the final migration structure and new features.
33. Added `timezone` setting overriding via `config.yaml` + Admin Settings mapping.
34. Globally replaced native SQLite UTC triggers (`CURRENT_TIMESTAMP`) and Python `datetime.utcnow()` with `zoneinfo` timezone-aware strings across `bsm.db` and runtime logs (`cron_state.py`).
35. Updated `Next.js` frontend ISO string extraction `dt.endsWith("Z")` guards for legacy payloads natively.
36. **[Bugfix] Negative timestamp display**: Identified root cause — `_now()` in `src/bsm/db.py` stored `Asia/Shanghai` local time without timezone info; frontend `timeAgo()` appended `Z` treating it as UTC, producing an 8-hour future offset and negative diffs (e.g. `-16248 秒前`). Fixed `_now()` to return UTC+Z. Removed forced `Z` appending in all three frontend `timeAgo()` calls; added `diff < 0 → 刚刚` guard throughout.
37. **Global 401 Handling**: Refactored the entire frontend application to use a centralized API client (`apiGet`, `apiPost`, etc.) that automatically intercepts 401 responses. Added a 5-second countdown toast and logout/redirect handling in the frontend.
38. **Security Hardening**: Modified backend `HTTPBasic` to use `auto_error=False`, preventing browser-native auth prompts and allowing the frontend to handle 401 JSON responses gracefully. Added comprehensive `tests/test_auth_enforcement.py` and updated existing router tests to verify authentication requirements for all protected endpoints.
39. **Login UI Cleanup**: Removed default test credentials and hint text from the login page to prepare the application for production use.
40. **Log Auto-Scroll Fix**: Updated the system log window in `/admin/settings` to use a non-intrusive auto-scroll mechanism (`scrollTop`) that avoids shifting browser focus or causing page jumps.
41. **API Client bugfix**: Fixed a bug where `apiDelete` was not passing the request path to the global response handler.64. **Product Dashboard Aggregation**: Addressed scaling complexities with heavily bundled user listings by introducing a true `/product/[id]` root dashboard that abstracts prices to global min/max scopes.
65. **Market List Linking Navigation**: Adapted all existing grid items to natively route to `/product/[id]` on-click. Also included a quick "查看商品" navigation button inside the package item detail view.
66. **Hydration Conflict Resolution**: Tracked down a React 15 SSR hydration panic (`<a>` descendant of `<a>`) triggered by nested HPoi search links inside bundle objects. Resolved by transitioning Next.js `<Link>` layouts to standard `<div>` clicks mapping `window.open`. 

### Files Touched

**New:**
- `tests/test_auth_enforcement.py`
- `src/frontend/src/components/ClientToaster.tsx`

**Modified:**
- `src/backend/auth.py`, `src/backend/routers/*.py`
- `src/frontend/src/lib/api.ts`
- `src/frontend/src/app/layout.tsx`
- `src/frontend/src/app/page.tsx`
- `src/frontend/src/app/market/page.tsx`, `market/[id]/page.tsx`
- `src/frontend/src/app/app/page.tsx`
- `src/frontend/src/app/notifications/page.tsx`
- `src/frontend/src/app/admin/settings/page.tsx`
- `tests/test_market_router.py` (and other test files)
- `doc/CHANGELOG.md`, `doc/WORKLOG.md`

### Verification

- Backend: `pytest tests/` → 72 passed, 0 failed.
- Security: Unauthorized access to `/api/settings` returns 401 JSON, not a browser prompt.
- UI: `/market` correctly redirects to login when not authenticated.
- UI: Admin settings log window automatically scrolls without page jumps.
- UI: Login page is empty by default (no "touko/admin" placeholder).

### Remaining

- Production deployment (nginx/caddy reverse proxy, Docker, etc.) not yet defined.

## 2026-03-03 User Experience & Account Logic Polishing

### Planned

- Fix 422 error on user creation with empty password.
- Allow regular users to access market refresh settings.
- Style "Delete User" button to red.
- Fix account update logic (renaming users created new accounts).
- Increase market page items to 20.
- Refine header UI with a user dropdown menu.

### Step Log

1. Modified `src/backend/routers/accounts.py` to handle `password: ""` as a sentinel for "no change" and fixed 422 validation for admins.
2. Added `/api/account/settings` in `src/backend/routers/settings.py` for regular user access.
3. Updated `src/frontend/src/app/market/page.tsx` to use the new settings endpoint.
4. Styled "Delete" button in `AccountManagementPanel.tsx`.
5. Refactored `api_upsert_account` into separate `POST` and `PUT` endpoints to support renames.
6. Updated `AccountManagementPanel.tsx` with `originalUsername` state and `apiPut` integration.
7. Synchronized backend `market.py` and frontend `page.tsx` default limits to 20.
8. Implemented `Shell.tsx` dropdown with click-outside listener and new CSS in `globals.css`.
9. Updated test suite; verified 29 tests pass including new rename/update scenarios.

### Verification

- `pytest tests/test_accounts_router.py tests/test_market_router.py` → All passed.
- Manual verification of dropdown behavior and red button styling.
