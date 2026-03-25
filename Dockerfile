# --- Frontend bundle (esbuild) ---
FROM node:22-bookworm-slim AS frontend
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY esbuild.mjs tsconfig.json ./
COPY src/frontend ./src/frontend
RUN npm run build

# --- Flask app ---
FROM python:3.13-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/backend ./src/backend
COPY src/frontend/templates ./src/frontend/templates
COPY scripts/ensure_schema.py ./scripts/ensure_schema.py
COPY --from=frontend /app/dist ./dist

ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Heroku sets PORT; local Docker Compose leaves it unset → default 8000
# --forwarded-allow-ips: Heroku router sends X-Forwarded-Proto; needed with ProxyFix for https URLs
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-8000} --forwarded-allow-ips='*' backend.main:application"]
