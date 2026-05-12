#!/bin/sh
# ──────────────────────────────────────────────────────────────────────────
# Boot script: runs FastAPI (sidecar) + Next.js inside ONE container.
# FastAPI binds to 127.0.0.1:8765 (private, only Next.js proxy talks to it).
# Next.js binds to 0.0.0.0:$PORT (public; this is what Render exposes).
# ──────────────────────────────────────────────────────────────────────────
set -e

# ── 1. Set up persistent state directory ────────────────────────────────
# If Render mounted a disk at /data, link pipeline/state there.
# Otherwise just use the local folder.
if [ -d /data ]; then
  echo "[start.sh] Persistent disk found at /data — linking pipeline/state to it"
  mkdir -p /data/state/images
  rm -rf /app/pipeline/state 2>/dev/null || true
  ln -sf /data/state /app/pipeline/state
else
  echo "[start.sh] No persistent disk — using ephemeral pipeline/state"
  mkdir -p /app/pipeline/state/images
fi

# ── 2. Bootstrap empty state files if missing ──────────────────────────
cd /app
[ -f pipeline/state/runs.json ]          || echo "[]"               > pipeline/state/runs.json
[ -f pipeline/state/batches.json ]       || echo '{"batches":[]}'   > pipeline/state/batches.json
[ -f pipeline/state/topic_library.json ] || echo '{"topics":[]}'    > pipeline/state/topic_library.json
[ -f pipeline/state/users.json ]         || echo "[]"               > pipeline/state/users.json

# ── 3. Start FastAPI in the background (localhost only) ─────────────────
echo "[start.sh] Starting FastAPI sidecar on 127.0.0.1:8765"
python -m uvicorn pipeline.service.app:app \
    --host 127.0.0.1 --port 8765 \
    --log-level info &
FASTAPI_PID=$!

# Clean shutdown on signal
trap "echo '[start.sh] Shutting down...'; kill $FASTAPI_PID 2>/dev/null; exit 0" TERM INT

# Give FastAPI a moment to bind
sleep 3

# ── 4. Start Next.js in the foreground on the platform port ─────────────
echo "[start.sh] Starting Next.js on 0.0.0.0:${PORT:-10000}"
exec npx next start -H 0.0.0.0 -p "${PORT:-10000}"
