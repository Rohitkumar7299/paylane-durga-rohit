#!/usr/bin/env bash
# Start paylane in state S1: services as host processes, datastores in Docker.
#
#   ./scripts/start-s1.sh     start everything
#   ./scripts/stop-s1.sh      stop everything
#
# Logs go to logs/<service>.log, PIDs to .pids/<service>.pid
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p logs .pids

export DATABASE_URL="${DATABASE_URL:-postgresql://paylane:paylane_dev_pw@localhost:5432/paylane}"
export REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"
export PYTHONUNBUFFERED=1

start_py() {
  local name=$1 port=$2 module=$3
  shift 3
  echo "starting $name on :$port"
  ( cd "$ROOT/services/$name" && \
    env "$@" setsid nohup python3 -m uvicorn "$module" --host 0.0.0.0 --port "$port" \
      > "$ROOT/logs/$name.log" 2>&1 < /dev/null &
    echo $! > "$ROOT/.pids/$name.pid" )
}

start_py mandate-svc 3001 app.main:app
start_py payment-svc 3002 app.main:app "MANDATE_SVC_URL=http://localhost:3001"
start_py ledger-svc  3003 app.main:app

echo "starting settlement-worker"
( cd "$ROOT/services/settlement-worker" && \
  setsid nohup python3 worker.py > "$ROOT/logs/settlement-worker.log" 2>&1 < /dev/null &
  echo $! > "$ROOT/.pids/settlement-worker.pid" )

echo "starting portal on :3000"
( cd "$ROOT/services/portal" && \
  env "PAYMENT_SVC_URL=http://localhost:3002" \
      "MANDATE_SVC_URL=http://localhost:3001" \
      "LEDGER_SVC_URL=http://localhost:3003" \
      setsid nohup node src/app.js > "$ROOT/logs/portal.log" 2>&1 < /dev/null &
  echo $! > "$ROOT/.pids/portal.pid" )

sleep 6
echo
echo "health:"
for p in 3001 3002 3003 3000; do
  printf "  :%s  " "$p"
  curl -s --max-time 5 "http://localhost:$p/health" || echo "(not responding)"
  echo
done
echo
echo "portal:  http://localhost:3000"
