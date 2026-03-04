#!/usr/bin/env bash
# BiliMartMonitor — build and run the Cloudflare Container Docker image locally
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

IMAGE_NAME="bsm-container"
PORT=8080

echo "Checking if Docker is running..."
if ! docker info >/dev/null 2>&1; then
    echo "Error: Docker daemon is not running."
    echo "Please start Docker Desktop or your Docker service and try again."
    exit 1
fi

echo "Building Docker image: $IMAGE_NAME ..."
# Ensure no architecture mismatches if you're on Apple Silicon vs Cloudflare (linux/amd64), 
# but for local running we can just build natively.
docker build -t "$IMAGE_NAME" -f Dockerfile.CloudFlare .

echo "Stopping any existing container named $IMAGE_NAME ..."
docker rm -f "$IMAGE_NAME" 2>/dev/null || true

echo "Starting Docker container on http://localhost:$PORT ..."
echo ""
echo "  ✅  Server → http://localhost:$PORT"
echo "  Press Ctrl+C to stop."
echo ""

docker run --rm -it \
  --name "$IMAGE_NAME" \
  -p "$PORT":8080 \
  -v "$(pwd)/.deployment.env:/app/.env" \
  -v "$(pwd)/config.yaml:/app/config.yaml" \
  -v "$(pwd)/data:/app/data" \
  "$IMAGE_NAME"
