# Application Architecture

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3 · FastAPI · uvicorn |
| Backend venv | `src/backend/.venv` (pyvenv) |
| Frontend | Next.js 15 · App Router · TypeScript |
| Frontend pkg | pnpm |
| Database | SQLite (dev) / Cloudflare D1 (prod) via SQLAlchemy |
| Business logic | `src/bsm/` — unchanged from pre-migration |

## Directory Layout

```
BiliMartMonitor/
├── src/backend/                  ← FastAPI application package
│   ├── .venv/                ← pyvenv (not committed)
│   ├── requirements.txt      ← FastAPI, uvicorn, python-dotenv, etc.
│   ├── main.py               ← App entry point, CORS, router mounts
│   ├── auth.py               ← authenticate_credentials, seed admin
│   ├── backend.py            ← Bili session / QR helpers
│   └── routers/
│       ├── auth.py           ← /api/auth/* + /api/ws/auth
│       ├── sessions.py       ← /api/admin/sessions/* + WS
│       ├── qr.py             ← /api/admin/qr/* + WS
│       ├── market.py         ← /api/market/*
│       └── settings.py       ← /api/settings/*, /api/settings/db-ping, user notification settings + test push
├── src/frontend/                 ← Next.js application
│   ├── src/
│   │   ├── app/              ← App Router pages (10 pages)
│   │   │   ├── page.tsx               →  /         (login)
│   │   │   ├── app/page.tsx           →  /app      (user dashboard)
│   │   │   ├── market/page.tsx        →  /market
│   │   │   ├── rules/page.tsx         →  /rules
│   │   │   ├── notifications/page.tsx →  /notifications
│   │   │   ├── account/page.tsx       →  /account
│   │   │   ├── admin/page.tsx         →  /admin
│   │   │   ├── admin/sessions/page.tsx →  /admin/sessions
│   │   │   ├── admin/users/page.tsx   →  /admin/users
│   │   │   └── admin/settings/page.tsx →  /admin/settings
│   │   ├── components/
│   │   │   └── Shell.tsx     ← App shell (header, nav, content)
│   │   ├── contexts/
│   │   │   └── AuthContext.tsx ← cookie-backed auth state
│   │   └── lib/
│   │       └── api.ts        ← apiGet / apiPost / apiDelete + BsmWsChannel
│   └── next.config.ts        ← /api/* → http://localhost:8000 proxy
│
├── src/bsm/                  ← Core business logic (unchanged)
│   ├── db.py                 ← SQLAlchemy-backed DB access
│   ├── api.py                ← Bilibili API (QR login, nav)
│   ├── env.py, settings.py   ← .env config
│   ├── notify.py, telegrambot.py ← Notification dispatchers
│   └── scan.py, cli.py, mall.py  ← Scan orchestration
│
├── src/bsm-cli/              ← Python CLI / utility entrypoints
│   ├── login.py              ← Create / refresh Bilibili session
│   ├── cron.py               ← Legacy polling runner
│   ├── scan.py               ← One-shot scan helper
│   ├── query.py              ← Query items from DB
│   └── migrate_env.py        ← Local config sanitizing helper
│
├── scripts/                  ← Shell-only dev / ops helper scripts
│   ├── run-backend.sh        ← Start FastAPI only
│   ├── run-frontend.sh       ← Start Next.js only
│   ├── run-docker.sh         ← Local Cloudflare container simulation
│   └── deploy-cf.sh          ← Cloudflare deployment entrypoint
│
├── tests/                    ← Python unit tests (src/bsm/* coverage)
├── .env                      ← Runtime config (not committed)
├── requirements.txt          ← Root Python deps (non-backend)
└── scripts/run.sh            ← Start backend + frontend together
```

## Port Map

| Service | Port | Notes |
|---|---|---|
| FastAPI (uvicorn) | 8000 | `--reload` in dev |
| Next.js | 3000 | `pnpm dev` |
| API proxy | via Next.js rewrites | `/api/*` → `:8000/api/*` |

## API Endpoints

### REST (XHR)

| Method | Path | Description |
|---|---|---|
| POST | /api/auth/login | username+password → role+redirect |
| GET | /api/auth/me | return current cookie-backed login state |
| POST | /api/auth/logout | clear session cookie |
| GET | /api/admin/sessions | list Bili sessions |
| DELETE | /api/admin/sessions/{username} | logout a Bili session |
| GET | /api/admin/qr/create | generate QR login code |
| POST | /api/admin/qr/poll | poll QR login result |
| GET | /api/settings/db-ping | test database connection latency |
| GET | /api/settings/db-size | database size diagnostics (table rows/bytes, recent growth) |
| GET | /api/settings/logs | read recent in-memory scan logs |
| GET | /api/settings/user-notifications | read one user's notification config |
| PUT | /api/settings/user-notifications | update one user's notification config |
| POST | /api/settings/user-notifications/test | send a test message to one user's Telegram IDs |
| GET | /health | health check |

### WebSocket (WS) — dual-stack

| Path | Actions |
|---|---|
| /api/ws/auth | `login`, `logout` |
| /api/ws/admin/sessions | `list`, `delete` |
| /api/ws/admin/qr | `create`, `poll` |

All WS messages use `{action, _id, ...payload}` format. `_id` is echoed back for request/response correlation.

## Auth Model

- **Server-side session cookie**: login issues `HttpOnly` signed cookie (`bsm_session`).
- Frontend restores auth state via `GET /api/auth/me`.
- Login returns `{ok, username, role, redirect}` and sets the cookie.
- Role-gated routes enforced client-side in the Shell component.
- Source of truth for users: `access_users` table in the configured database.
- User notification fields (`keywords`, `telegram_ids`, `notify_enabled`) are stored in `access_users`.
- Project-root `config.yaml` is used for mutable system settings such as `scan_mode`, `interval`, `category`, `timezone`, and global Telegram bot credentials.

## Navigation Notes

- Admin navigation no longer exposes a separate `管理后台` entry; `/admin` redirects to `/admin/settings`.
- User navigation no longer exposes a separate `我的规则` entry; `/rules` redirects to `/notifications`.
- The `/notifications` page now contains both personal notification configuration and rule guidance.

## User Roles

| Role | Access |
|---|---|
| `guest` | Login page only |
| `user` | All `/app/*` pages |
| `admin` | All pages including `/admin/*` |

## Running Locally

```bash
# One command — starts both services
./scripts/run.sh

# Or separately:
src/backend/.venv/bin/uvicorn --app-dir src backend.main:app --port 8000 --reload
cd src/frontend && pnpm dev
```

## Testing

```bash
# Backend business logic (src/bsm/*)
BSM_TESTING=1 .venv/bin/python3 -m pytest tests/ -v
```
