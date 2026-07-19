#!/usr/bin/env bash
# Stop everything started by start-s1.sh
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
for f in .pids/*.pid; do
  [ -e "$f" ] || continue
  pid=$(cat "$f")
  name=$(basename "$f" .pid)
  if kill -0 "$pid" 2>/dev/null; then
    echo "stopping $name (pid $pid)"
    kill "$pid" 2>/dev/null || true
  fi
  rm -f "$f"
done
pkill -f "uvicorn app.main:app" 2>/dev/null || true
pkill -f "python3 worker.py" 2>/dev/null || true
pkill -f "node src/app.js" 2>/dev/null || true
echo "stopped"
