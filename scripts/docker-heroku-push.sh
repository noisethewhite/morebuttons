#!/usr/bin/env bash
# Build for Heroku (linux/amd64) and push to registry.heroku.com.
# Usage: HEROKU_APP_NAME=your-app npm run docker:heroku
set -euo pipefail

if [[ -z "${HEROKU_APP_NAME:-}" ]]; then
  echo "Set HEROKU_APP_NAME to your Heroku app name, e.g.:" >&2
  echo "  HEROKU_APP_NAME=morebuttons npm run docker:heroku" >&2
  exit 1
fi

IMAGE="registry.heroku.com/${HEROKU_APP_NAME}/web"

heroku container:login

# linux/amd64: Heroku dynos are x86_64; default arm64 builds fail or get "unsupported" on push.
# --provenance=false: Heroku's registry rejects OCI attestations ("unsupported").
docker buildx build \
  --platform linux/amd64 \
  --provenance=false \
  --sbom=false \
  -t "${IMAGE}" \
  --push \
  .

echo "Pushed ${IMAGE}"
