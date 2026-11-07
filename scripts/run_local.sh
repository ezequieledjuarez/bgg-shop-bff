#!/usr/bin/env bash
set -euo pipefail

BFF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT_DIR="$(cd -- "$BFF_DIR/.." && pwd)"

cd -- "$BFF_DIR"
FLASK_SKIP_DOTENV=1 exec "$BFF_DIR/.venv/bin/python" -m flask \
    --env-file "$ROOT_DIR/.env" --app app:app run --host 127.0.0.1 --port 5000
