#!/usr/bin/env bash
# BiliMartMonitor — Deploy the Cloudflare Container

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "Checking Next.js and Hono wrapper dependencies..."
if [ ! -d "node_modules" ] || [ ! -d "src/frontend/node_modules" ]; then
    echo "Installing missing dependencies..."
    npm install
    (cd src/frontend && pnpm install)
fi

echo "=========================================================="
echo "🚀 Deploying BiliMartMonitor as a Cloudflare Container..."
echo "=========================================================="
echo ""

# The deployment relies on wrangler.jsonc and Dockerfile.CloudFlare
npx wrangler deploy

echo ""
echo "=========================================================="
echo "✅ Deployment process finished."
echo "=========================================================="
