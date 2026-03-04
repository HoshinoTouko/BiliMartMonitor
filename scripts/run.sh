#!/usr/bin/env bash
# BiliMartMonitor — start backend (FastAPI) and frontend (Next.js) together
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# ---------------------------------------------------------------------------
# Backend — FastAPI via pyvenv
# ---------------------------------------------------------------------------
PYTHON_BIN="src/backend/.venv/bin/python3"
if [ ! -x "$PYTHON_BIN" ]; then
  echo "Backend venv not found. Creating..."
  python3 -m venv src/backend/.venv
  src/backend/.venv/bin/pip install -r src/backend/requirements.txt -q
fi

echo "Starting FastAPI backend on http://localhost:8000 …"
"$PYTHON_BIN" -m uvicorn backend.main:app --app-dir "$REPO_ROOT/src" --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

# ---------------------------------------------------------------------------
# Frontend — Next.js via pnpm
# ---------------------------------------------------------------------------
if [ ! -d "src/frontend/node_modules" ]; then
  echo "Installing frontend dependencies..."
  (cd src/frontend && pnpm install)
fi

echo "Starting Next.js frontend on http://localhost:3000 …"
(cd src/frontend && pnpm dev) &
FRONTEND_PID=$!

# ---------------------------------------------------------------------------
# Cleanup on exit
# ---------------------------------------------------------------------------
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0" INT TERM

echo ""
echo "  ✅  Backend  → http://localhost:8000"
echo "  ✅  Frontend → http://localhost:3000"
echo "  Press Ctrl+C to stop both."
echo ""

wait
