#!/usr/bin/env bash
# Runs acceptance tests A1-A7 (each test uses its own temp DB and server; your dev DB is untouched)
# and type-checks/builds the frontend.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT/backend"
[ -d .venv ] || "${PYTHON:-python3}" -m venv .venv
.venv/bin/pip install -q -r requirements.txt
.venv/bin/python -m pytest -v tests
cd "$ROOT/frontend"
[ -d node_modules ] || npm install --no-audit --no-fund
npm run build
