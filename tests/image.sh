#!/usr/bin/env bash
set -euo pipefail

image=${1:?usage: tests/image.sh IMAGE}
network=egress-image-$$
containers=()

stop() {
  for container in "${containers[@]}"; do docker rm -f "$container" >/dev/null 2>&1 || true; done
  docker network rm "$network" >/dev/null 2>&1 || true
}
trap stop EXIT

fail() {
  echo "::error::$1" >&2
  exit 1
}

start() {
  containers+=("$(docker run -d --network "$network" --read-only "$@")")
}

address() {
  docker port "$1" 8000/tcp | head -1
}

healthy() {
  for _ in $(seq 1 60); do
    [ "$(docker inspect -f '{{.State.Health.Status}}' "$1")" = healthy ] && return 0
    sleep 0.5
  done
  docker logs "$1" >&2
  fail "container $1 never became healthy"
}

request() {
  curl -s -o /dev/null -w '%{http_code} %header{x-egress-failure}' "$@"
}

expect() {
  local actual
  actual=$(request "${@:3}")
  [ "$actual" = "$2" ] || fail "$1: expected '$2', got '$actual'"
  echo "ok: $1 ($actual)"
}

docker network create "$network" >/dev/null
start --entrypoint python "$image" -m http.server 8080
target=${containers[-1]}
target_address=$(docker inspect -f "{{(index .NetworkSettings.Networks \"$network\").IPAddress}}" "$target")

start -p 127.0.0.1::8000 -e PROXY__KEY=secret -e PROXY__ALLOW_LOCAL=true "$image" --workers 2
open=${containers[-1]}
start -p 127.0.0.1::8000 -e PROXY__KEY=secret "$image"
guarded=${containers[-1]}
healthy "$open"
healthy "$guarded"

expect "request without the key is refused" "401 unauthorized" "http://$(address "$open")/" \
  -H "x-egress-target: http://$target_address:8080/"
expect "request is forwarded to the target" "200 " "http://$(address "$open")/" \
  -H "x-egress-key: secret" -H "x-egress-target: http://$target_address:8080/"
expect "private target is refused by default" "400 invalid" "http://$(address "$guarded")/" \
  -H "x-egress-key: secret" -H "x-egress-target: http://$target_address:8080/"

started=$SECONDS
docker stop "$open" >/dev/null
elapsed=$(( SECONDS - started ))
code=$(docker inspect -f '{{.State.ExitCode}}' "$open")
[ "$code" = 0 ] || fail "stop: exit code $code"
[ "$elapsed" -lt 5 ] || fail "stop: took ${elapsed}s, SIGTERM was probably ignored"
echo "ok: container stops on SIGTERM (exit $code, ${elapsed}s)"
