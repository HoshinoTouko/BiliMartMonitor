#!/usr/bin/env bash
# BiliMartMonitor — run backend Python test suite
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# ---------------------------------------------------------------------------
# Pick a Python that can run the full backend suite
# ---------------------------------------------------------------------------
PYTHON_BIN=""
for candidate in ".venv/bin/python" "src/backend/.venv/bin/python3" "python3"; do
  if ! command -v "$candidate" >/dev/null 2>&1; then
    continue
  fi
  if "$candidate" -c "import fastapi, sqlalchemy; from alembic import command" >/dev/null 2>&1; then
    PYTHON_BIN="$candidate"
    break
  fi
done

if [ -z "$PYTHON_BIN" ]; then
  echo "No existing Python environment can run the full test suite. Creating backend venv..."
  python3 -m venv src/backend/.venv
  src/backend/.venv/bin/pip install -r src/backend/requirements.txt -q
  src/backend/.venv/bin/pip install alembic -q
  PYTHON_BIN="src/backend/.venv/bin/python3"
fi

export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

echo "Running backend test suite..."
exec "$PYTHON_BIN" -m unittest discover -s src/backend/testsuite
