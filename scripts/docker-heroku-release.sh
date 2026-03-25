#!/usr/bin/env bash
# Release the pushed image to the web dyno.
# Usage: HEROKU_APP_NAME=your-app npm run docker:heroku:release
set -euo pipefail

if [[ -z "${HEROKU_APP_NAME:-}" ]]; then
  echo "Set HEROKU_APP_NAME, e.g.: HEROKU_APP_NAME=morebuttons npm run docker:heroku:release" >&2
  exit 1
fi

heroku container:release web -a "${HEROKU_APP_NAME}"
