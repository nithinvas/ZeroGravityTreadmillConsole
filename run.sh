#!/usr/bin/env bash
# Starts the TreadMill console. Arguments pass through to `treadmill serve`,
# e.g. ./run.sh --source sim   or   ./run.sh --nominal-rate 250
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"

if [ ! -f "$ROOT/frontend/dist/index.html" ]; then
  echo "Building the UI (first run)..."
  (cd "$ROOT/frontend" && npm install --no-audit --no-fund && npm run build)
fi

cd "$ROOT/backend"
exec uv run --python 3.12 treadmill serve "$@"
