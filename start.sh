#!/bin/sh
# ──────────────────────────────────────────────────────────────────────────
# Boot script: runs FastAPI (sidecar) + Next.js inside ONE container.
# FastAPI binds to 127.0.0.1:8765 (private, only Next.js proxy talks to it).
# Next.js binds to 0.0.0.0:$PORT (public; this is what Render exposes).
# ──────────────────────────────────────────────────────────────────────────
set -e

cd /app

# ── 1. Wire persistent state to Render's mounted disk ──────────────────
# IMPORTANT: pipeline/state/ contains BOTH Python code (batch_tracker.py,
# run_tracker.py, image_store.py, __init__.py) AND runtime data (*.json,
# images/). We only want to symlink the DATA to /data, never the code.
if [ -d /data ]; then
  echo "[start.sh] Persistent disk found at /data"
  mkdir -p /data/state/images

  # Bootstrap each JSON state file on the disk if missing
  [ -f /data/state/runs.json ]          || echo "[]"               > /data/state/runs.json
  [ -f /data/state/batches.json ]       || echo '{"batches":[]}'   > /data/state/batches.json
  [ -f /data/state/topic_library.json ] || echo '{"topics":[]}'    > /data/state/topic_library.json
  [ -f /data/state/users.json ]         || echo "[]"               > /data/state/users.json

  # Replace the in-image copies with symlinks to /data
  for f in runs.json batches.json topic_library.json users.json; do
    rm -f "pipeline/state/$f"
    ln -sf "/data/state/$f" "pipeline/state/$f"
  done

  # Replace images dir with symlink to /data
  rm -rf pipeline/state/images
  ln -sf /data/state/images pipeline/state/images
else
  echo "[start.sh] No persistent disk — using ephemeral pipeline/state/"
  mkdir -p pipeline/state/images
  [ -f pipeline/state/runs.json ]          || echo "[]"               > pipeline/state/runs.json
  [ -f pipeline/state/batches.json ]       || echo '{"batches":[]}'   > pipeline/state/batches.json
  [ -f pipeline/state/topic_library.json ] || echo '{"topics":[]}'    > pipeline/state/topic_library.json
  [ -f pipeline/state/users.json ]         || echo "[]"               > pipeline/state/users.json
fi

# ── 2. Start FastAPI in the background (localhost only) ─────────────────
echo "[start.sh] Starting FastAPI sidecar on 127.0.0.1:8765"
python -m uvicorn pipeline.service.app:app \
    --host 127.0.0.1 --port 8765 \
    --log-level info &
FASTAPI_PID=$!

# Clean shutdown on signal
trap "echo '[start.sh] Shutting down...'; kill $FASTAPI_PID 2>/dev/null; exit 0" TERM INT

# Give FastAPI a moment to bind
sleep 3

# ── 3. Start Next.js in the foreground on the platform port ─────────────
echo "[start.sh] Starting Next.js on 0.0.0.0:${PORT:-10000}"
exec npx next start -H 0.0.0.0 -p "${PORT:-10000}"
