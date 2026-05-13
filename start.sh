#!/bin/sh
# ──────────────────────────────────────────────────────────────────────────
# Boot script: runs FastAPI (sidecar) + Next.js inside ONE container.
# Resilient: failures in state setup don't abort the script.
# ──────────────────────────────────────────────────────────────────────────

cd /app || exit 1

echo "[start.sh] CWD: $(pwd)"
echo "[start.sh] pipeline/state contents BEFORE setup:"
ls -la pipeline/state/ 2>&1 || true

# ── 1. Wire persistent state to Render's mounted disk ──────────────────
if [ -d /data ]; then
  echo "[start.sh] Persistent disk found at /data"
  mkdir -p /data/state/images || true

  for entry in "runs.json:[]" "batches.json:{\"batches\":[]}" "topic_library.json:{\"topics\":[]}" "users.json:[]"; do
    name="${entry%%:*}"
    default="${entry#*:}"
    if [ ! -f "/data/state/$name" ]; then
      if [ -f "pipeline/state/$name" ] && [ ! -L "pipeline/state/$name" ]; then
        echo "[start.sh] Copying default $name to /data/state/"
        cp "pipeline/state/$name" "/data/state/$name" 2>&1 || true
      else
        echo "$default" > "/data/state/$name" 2>&1 || true
      fi
    fi
  done

  # Replace in-image data files with symlinks (Python code files stay put)
  for f in runs.json batches.json topic_library.json users.json; do
    if [ -e "pipeline/state/$f" ] && [ ! -L "pipeline/state/$f" ]; then
      rm -f "pipeline/state/$f" 2>&1 || true
    fi
    ln -sfn "/data/state/$f" "pipeline/state/$f" 2>&1 || true
  done

  # Images dir
  if [ -e pipeline/state/images ] && [ ! -L pipeline/state/images ]; then
    rm -rf pipeline/state/images 2>&1 || true
  fi
  ln -sfn /data/state/images pipeline/state/images 2>&1 || true

  # SEO state dir — embeddings, link graph, keyword clusters, scores, etc.
  mkdir -p /data/state/seo || true
  if [ -e pipeline/state/seo ] && [ ! -L pipeline/state/seo ]; then
    cp -rn pipeline/state/seo/. /data/state/seo/ 2>&1 || true
    rm -rf pipeline/state/seo 2>&1 || true
  fi
  ln -sfn /data/state/seo pipeline/state/seo 2>&1 || true

  # Ensure default admin user exists
  echo "[start.sh] Ensuring default admin user exists..."
  python -m pipeline.scripts.add_user bhavikvaid65@gmail.com --password=Cadialogue@2026 --name="Bhavik Vaid" --role=admin || true
else
  echo "[start.sh] No persistent disk — using ephemeral pipeline/state/"
  mkdir -p pipeline/state/images || true
  mkdir -p pipeline/state/seo || true
  # Ensure default admin user exists locally as well
  python -m pipeline.scripts.add_user bhavikvaid65@gmail.com --password=Cadialogue@2026 --name="Bhavik Vaid" --role=admin || true
fi

echo "[start.sh] pipeline/state contents AFTER setup:"
ls -la pipeline/state/ 2>&1 || true

# ── 2. Start FastAPI in the background ─────────────────────────────────
echo "[start.sh] Starting FastAPI sidecar on 127.0.0.1:8765"
python -m uvicorn pipeline.service.app:app \
    --host 127.0.0.1 --port 8765 \
    --log-level info &
FASTAPI_PID=$!
echo "[start.sh] FastAPI PID: $FASTAPI_PID"

# Clean shutdown on signal
trap "echo '[start.sh] Shutting down...'; kill $FASTAPI_PID 2>/dev/null; exit 0" TERM INT

# ── 3. Start Next.js in the foreground (MUST stay running) ──────────────
echo "[start.sh] Starting Next.js on 0.0.0.0:${PORT:-10000}"
exec npx next start -H 0.0.0.0 -p "${PORT:-10000}"
