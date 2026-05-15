#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

export MIMI_API_HOST="${MIMI_API_HOST:-127.0.0.1}"
export MIMI_API_PORT="${MIMI_API_PORT:-8765}"
export MIMI_ALLOWED_ORIGIN="${MIMI_ALLOWED_ORIGIN:-https://your-frontend.example.com}"

if [[ -n "${MIMI_API_KEY:-}" ]]; then
  export MIMI_API_KEY
fi

cd "$REPO_DIR"
exec "$PYTHON_BIN" scripts/local_stock_api.py
