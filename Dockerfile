# ─── Stage 1 — build Next.js ──────────────────────────────────────────────
FROM node:20-bookworm AS web-build

WORKDIR /app

# Install Node deps (use cache layer)
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund

# Build the Next.js app
COPY . .
RUN npm run build


# ─── Stage 2 — runtime (Python + Node + built Next.js) ───────────────────
FROM python:3.12-slim-bookworm AS runtime

# Install Node.js 20 (for running `next start`) and runtime deps
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates gnupg build-essential \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps
COPY pipeline/requirements.txt ./pipeline/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r pipeline/requirements.txt

# Copy node deps + built Next.js from stage 1
COPY --from=web-build /app/node_modules ./node_modules
COPY --from=web-build /app/.next ./.next
COPY --from=web-build /app/public ./public
COPY --from=web-build /app/package.json ./package.json
COPY --from=web-build /app/next.config.* ./

# Copy backend source
COPY pipeline ./pipeline
COPY lib ./lib
COPY components ./components
COPY app ./app
COPY middleware.ts ./middleware.ts
COPY tsconfig.json ./tsconfig.json
COPY start.sh ./start.sh
RUN chmod +x ./start.sh

# Render mounts a persistent disk here for all runtime state
RUN mkdir -p /data/state/images \
    && ln -sf /data/state /app/pipeline/state \
    || true

# Render uses PORT env var; default 10000
ENV PORT=10000
EXPOSE 10000

CMD ["./start.sh"]
