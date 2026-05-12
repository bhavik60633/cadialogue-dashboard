#!/bin/sh
# ──────────────────────────────────────────────────────────────────────────
# Boot script: runs FastAPI (sidecar) + Next.js inside ONE container.
# FastAPI binds to 127.0.0.1:8765 (private, only Next.js proxy talks to it).
# Next.js binds to 0.0.0.0:$PORT (public; this is what Render exposes).
# ──────────────────────────────────────────────────────────────────────────
set -e

# Ensure runtime state directory exists (Render persistent disk)
mkdir -p /data/state/images
# Bootstrap state files if missing
[ -f /data/state/runs.json ]          || echo "[]"           > /data/state/runs.json
[ -f /data/state/batches.json ]       || echo '{"batches":[]}'    > /data/state/batches.json
[ -f /data/state/topic_library.json ] || echo '{"topics":[]}'    > /data/state/topic_library.json
[ -f /data/state/users.json ]         || echo "[]"           > /data/state/users.json

# Start FastAPI in the background (binds to localhost only)
python -m uvicorn pipeline.service.app:app \
    --host 127.0.0.1 --port 8765 \
    --log-level info &

FASTAPI_PID=$!

# Trap to stop FastAPI cleanly when Next.js exits
trap "kill $FASTAPI_PID 2>/dev/null; exit 0" SIGTERM SIGINT

# Wait a moment for FastAPI to boot
sleep 3

# Start Next.js in the foreground on the platform-assigned port
exec npx next start -H 0.0.0.0 -p "${PORT:-10000}"
