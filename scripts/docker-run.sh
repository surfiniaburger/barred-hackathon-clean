#!/usr/bin/env bash
# docker-run.sh — run the container with the Baseten key injected from the
# host OS keychain at runtime, so it never lives in shell history or repo
# files (still visible via `docker inspect`, as with any -e variable).
#
# Usage:
#   ./scripts/docker-run.sh [extra docker run args...]
#
# The key resolves as: BASETEN_API_KEY env var, else host keychain item
# (service "barred-baseten", account "api_key"). Override the image with
# DOCKER_IMAGE and the host port with PORT.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${DOCKER_IMAGE:-barred}"
PORT="${PORT:-8080}"

KEY="$(python3 "$ROOT_DIR/scripts/baseten_key.py" 2>/dev/null || true)"
ARGS=()
if [ -n "${KEY:-}" ]; then
    ARGS+=(-e "BASETEN_API_KEY=$KEY")
else
    echo "warning: no Baseten key resolved (env var or host keychain); container starts without one" >&2
fi
unset KEY

exec docker run "${ARGS[@]}" -p "${PORT}:8080" "$@" "$IMAGE"
