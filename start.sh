#!/usr/bin/env bash
# One command: install deps, initialize demo data (idempotent), start backend + frontend.
#   ./start.sh          keep existing DB (seed only if empty)
#   ./start.sh --reset  rebuild DB from the quick-start dataset
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
PY="${PYTHON:-python3}"

cd "$ROOT/backend"
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/pip install -q -r requirements.txt
.venv/bin/python -m app.seed ${1:-}

cd "$ROOT/frontend"
[ -d node_modules ] || npm install --no-audit --no-fund

cd "$ROOT/backend"
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 &
API_PID=$!
trap 'kill $API_PID 2>/dev/null' EXIT INT TERM

cd "$ROOT/frontend"
echo "API: http://127.0.0.1:8000   UI: http://127.0.0.1:5173"
npm run dev -- --host 127.0.0.1
