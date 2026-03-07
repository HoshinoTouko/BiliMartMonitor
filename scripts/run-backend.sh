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
ALEMBIC_BIN="src/backend/.venv/bin/alembic"
if [ -x "$ALEMBIC_BIN" ]; then
    "$ALEMBIC_BIN" upgrade head
elif "$PYTHON_BIN" -c "from alembic.config import main; main(argv=['upgrade','head'])" >/dev/null 2>&1; then
    "$PYTHON_BIN" -c "from alembic.config import main; main(argv=['upgrade','head'])"
else
    echo "Warning: alembic not installed in src/backend/.venv (skip migrations)"
    echo "         Run: src/backend/.venv/bin/pip install alembic"
fi

# ---------------------------------------------------------------------------
# Run data migration (product + c2c_items_snapshot + detail_blob backfill)
# ---------------------------------------------------------------------------
RUN_DATA_MIGRATION="${BSM_RUN_DATA_MIGRATION:-1}"
if [ "$RUN_DATA_MIGRATION" = "1" ]; then
  echo "Running data migration for product/snapshot/blob..."
  if [ "${BSM_DATA_MIGRATION_RESET:-0}" = "1" ]; then
    echo "  BSM_DATA_MIGRATION_RESET=1 -> migration will reset product/snapshot tables first"
    PYTHONPATH=src "$PYTHON_BIN" src/bsm-cli/migrate_product_snapshot.py --reset
  else
    PYTHONPATH=src "$PYTHON_BIN" src/bsm-cli/migrate_product_snapshot.py
  fi
else
  echo "Skipping data migration (BSM_RUN_DATA_MIGRATION=$RUN_DATA_MIGRATION)"
fi


echo "Starting FastAPI backend on http://localhost:8000 …"
echo "  Press Ctrl+C to stop."
echo ""

exec "$PYTHON_BIN" -m uvicorn backend.main:app \
  --app-dir "$REPO_ROOT/src" \
  --host 0.0.0.0 --port 8000 --reload
