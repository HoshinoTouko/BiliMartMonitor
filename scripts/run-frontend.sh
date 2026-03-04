#!/usr/bin/env bash
# BiliMartMonitor — start Next.js frontend only
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# ---------------------------------------------------------------------------
# Kill any stale process on port 3000
# ---------------------------------------------------------------------------
STALE=$(lsof -ti :3000 2>/dev/null || true)
if [ -n "$STALE" ]; then
  echo "Killing stale process(es) on port 3000: $STALE"
  kill $STALE 2>/dev/null || true
  sleep 0.5
fi

# ---------------------------------------------------------------------------
# Ensure node_modules
# ---------------------------------------------------------------------------
if [ ! -d "src/frontend/node_modules" ]; then
  echo "Installing frontend dependencies..."
  (cd src/frontend && pnpm install)
fi

echo "Starting Next.js frontend on http://localhost:3000 …"
echo "  Press Ctrl+C to stop."
echo ""

cd src/frontend
exec pnpm dev
