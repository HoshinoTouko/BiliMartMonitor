# syntax=docker/dockerfile:1

# Stage 1: Build the Next.js frontend (Standalone)
FROM node:20-alpine AS frontend-builder
WORKDIR /app/src/frontend
RUN corepack enable pnpm
COPY src/frontend/package.json src/frontend/pnpm-lock.yaml* src/frontend/pnpm-workspace.yaml* ./
RUN pnpm install --frozen-lockfile
COPY src/frontend/ ./
ENV NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

# Stage 2: Final runner (Python + Node.js)
FROM python:3.11-slim AS runner

# Install Node.js runtime and essential build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    libsqlite3-dev \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python backend dependencies
COPY src/backend/requirements.txt ./src/backend/
RUN pip install --no-cache-dir -r src/backend/requirements.txt

# Copy application source code
COPY src/ ./src/

# Copy the pre-built Next.js standalone folder and assets
COPY --from=frontend-builder /app/src/frontend/.next/standalone ./frontend/
COPY --from=frontend-builder /app/src/frontend/.next/static ./frontend/.next/static
COPY --from=frontend-builder /app/src/frontend/public ./frontend/public

# Default environment variables
ENV HOST=0.0.0.0
ENV PORT=8080
ENV PYTHONPATH=/app/src
ENV ENVIRONMENT=production

# Entrypoint script to coordinate FastAPI and Next.js
RUN echo '#!/bin/bash\n\
    # Start FastAPI backend in the background (Internal port 8000)\n\
    uvicorn --app-dir /app/src backend.main:app --host 127.0.0.1 --port 8000 &\n\
    # Wait for backend to initialize\n\
    sleep 2\n\
    # Start Next.js standalone server (Primary port $PORT)\n\
    export HOSTNAME=0.0.0.0\n\
    cd /app/frontend && node server.js\n\
    ' > /app/start.sh && chmod +x /app/start.sh

EXPOSE 8080

CMD ["/app/start.sh"]
