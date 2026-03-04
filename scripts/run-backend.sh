#!/usr/bin/env bash
# BiliMartMonitor — start FastAPI backend only
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# ---------------------------------------------------------------------------
# Kill any stale process on port 8000
# ---------------------------------------------------------------------------
STALE=$(lsof -ti :8000 2>/dev/null || true)
if [ -n "$STALE" ]; then
  echo "Killing stale process(es) on port 8000: $STALE"
  kill $STALE 2>/dev/null || true
  sleep 0.5
fi

# ---------------------------------------------------------------------------
# Ensure venv exists
# ---------------------------------------------------------------------------
PYTHON_BIN="src/backend/.venv/bin/python3"
if [ ! -x "$PYTHON_BIN" ]; then
  echo "Backend venv not found. Creating..."
  python3 -m venv src/backend/.venv
  src/backend/.venv/bin/pip install -r src/backend/requirements.txt -q
fi

# ---------------------------------------------------------------------------
# Run Database Migrations
# ---------------------------------------------------------------------------
echo "Running database migrations..."
if [ -x ".venv/bin/alembic" ]; then
    .venv/bin/alembic upgrade head
else
    echo "Warning: alembic not found in .venv/bin/"
fi


echo "Starting FastAPI backend on http://localhost:8000 …"
echo "  Press Ctrl+C to stop."
echo ""

exec "$PYTHON_BIN" -m uvicorn backend.main:app \
  --app-dir "$REPO_ROOT/src" \
  --host 0.0.0.0 --port 8000 --reload
