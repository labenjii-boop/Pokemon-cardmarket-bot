#!/bin/bash
# One-command way to try the app before it's packaged into a real .dmg (Phase 11).
# Sets up the backend, seeds it with real data on first run only, starts both the backend and
# frontend dev servers, and opens the app in your browser. Ctrl+C stops everything.
#
# Still needs Python 3 and Node.js installed first — see README.md if you don't have those.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/apps/backend"
DESKTOP_DIR="$SCRIPT_DIR/apps/desktop"

command -v python3 >/dev/null 2>&1 || {
  echo "Python 3 not found. Install it from https://www.python.org/downloads/ (or 'brew install python3'), then run this script again."
  exit 1
}
command -v node >/dev/null 2>&1 || {
  echo "Node.js not found. Install it from https://nodejs.org, then run this script again."
  exit 1
}

echo "==> Setting up the backend..."
cd "$BACKEND_DIR"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt

if [ ! -f .seeded ]; then
  echo "==> First run: loading the card catalog, exchange rates, and today's prices (a few minutes, one time only)..."
  python scripts/import_catalog.py
  python scripts/sync_fx.py
  python scripts/poll_snapshots.py
  touch .seeded
fi

echo "==> Starting the backend..."
python -m app.entrypoint &
BACKEND_PID=$!

cleanup() {
  echo ""
  echo "==> Stopping..."
  kill "$BACKEND_PID" 2>/dev/null
}
trap cleanup EXIT INT TERM

echo "==> Setting up the frontend (first run only takes a minute)..."
cd "$DESKTOP_DIR"
npm install --silent

echo "==> Opening the app in your browser..."
( sleep 3 && open "http://localhost:1420" 2>/dev/null ) &

npm run dev
