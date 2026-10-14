#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

upstream=19001
egress=19000
duration=${DURATION:-5s}
pids=()

stop() {
  for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap stop EXIT

ready() {
  for _ in $(seq 1 50); do
    curl -s -o /dev/null "http://127.0.0.1:$1/" && return 0
    sleep 0.2
  done
  echo "nothing answered on port $1" >&2
  exit 1
}

load() {
  wrk -t"$(( $2 < 4 ? $2 : 4 ))" -c"$2" -d"$duration" --latency \
    -H "x-egress-key: benchmark" -H "x-egress-target: http://127.0.0.1:$upstream$1" \
    "http://127.0.0.1:$egress/" | awk -v label="$3" '
      /Requests\/sec/ {rps = $2}
      /^ +50%/ {p50 = $2}
      /^ +99%/ {p99 = $2}
      /Non-2xx|Socket errors/ {errors = errors " | " $0}
      END {printf "%-28s %10s req/s   p50 %-9s p99 %-9s%s\n", label, rps, p50, p99, errors}'
}

serve='import sys, uvicorn
from egress_proxy.server.main import immediate
uvicorn.Config.bind_socket = immediate(uvicorn.Config.bind_socket)
uvicorn.main.main(args=sys.argv[1:])'
taskset -c 2-5 uv run python -c "$serve" benchmarks.upstream:app --port "$upstream" --workers 4 \
  --http httptools --no-access-log --log-level warning &
pids+=($!)
PROXY__KEY=benchmark taskset -c 0 uv run egress-proxy --port "$egress" --log-level warning "$@" &
pids+=($!)
ready "$upstream"
ready "$egress"

load /small 1 "100 B, 1 connection"
load /small 16 "100 B, 16 connections"
load /small 64 "100 B, 64 connections"
load /large 16 "1 MB, 16 connections"
