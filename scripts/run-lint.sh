#!/usr/bin/env bash
# BiliMartMonitor — run lint and static checks
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# ---------------------------------------------------------------------------
# Pick a Python interpreter
# ---------------------------------------------------------------------------
PYTHON_BIN=""
for candidate in ".venv/bin/python" "src/backend/.venv/bin/python3" "python3"; do
  if command -v "$candidate" >/dev/null 2>&1; then
    PYTHON_BIN="$candidate"
    break
  fi
done

if [ -z "$PYTHON_BIN" ]; then
  echo "Python 3 is required to run backend lint checks."
  exit 1
fi

export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

# ---------------------------------------------------------------------------
# Backend — prefer ruff when available, otherwise do syntax checks
# ---------------------------------------------------------------------------
if "$PYTHON_BIN" -m ruff --version >/dev/null 2>&1; then
  echo "Running Python lint with ruff..."
  "$PYTHON_BIN" -m ruff check src src/backend/testsuite
else
  echo "ruff not available; running Python syntax checks..."
  "$PYTHON_BIN" -m compileall -q src src/backend/testsuite
fi

# ---------------------------------------------------------------------------
# Frontend — ESLint via pnpm
# ---------------------------------------------------------------------------
if [ ! -d "src/frontend/node_modules" ]; then
  echo "Installing frontend dependencies..."
  (cd src/frontend && pnpm install)
fi

echo "Running frontend lint..."
(cd src/frontend && pnpm lint)
