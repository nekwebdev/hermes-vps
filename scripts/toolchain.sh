#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 '<command>'" >&2
  exit 64
fi

CMD="$1"
WORKDIR="$(pwd)"
TOOLCHAIN_QUIET="${TOOLCHAIN_QUIET:-0}"
NIX_QUIET_ARGS=()
if [[ "$TOOLCHAIN_QUIET" == "1" ]]; then
  NIX_QUIET_ARGS+=(--quiet)
fi

if [[ -f "${WORKDIR}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${WORKDIR}/.env"
  set +a
fi

# shellcheck disable=SC2016
STRICT_FLAKE_RUNNER='set -euo pipefail
FLAKE_PATH="$(printf "%s" "$PATH" | tr ":" "\n" | awk "/^\\/nix\\/store\\//" | paste -sd: -)"
if [[ -z "${FLAKE_PATH}" ]]; then
  echo "ERROR: flake tool PATH is empty inside nix develop." >&2
  exit 1
fi
export PATH="${FLAKE_PATH}"
exec bash -lc "$CODEX_CMD"'

if command -v nix >/dev/null 2>&1; then
  exec env CODEX_CMD="$CMD" STRICT_FLAKE_RUNNER="$STRICT_FLAKE_RUNNER" \
    nix --extra-experimental-features 'nix-command flakes' develop "${NIX_QUIET_ARGS[@]}" --impure "path:${WORKDIR}" --command bash -lc "$STRICT_FLAKE_RUNNER"
fi

if command -v docker >/dev/null 2>&1; then
  DOCKER_ENV_ARGS=()
  if [[ -f "${WORKDIR}/.env" ]]; then
    DOCKER_ENV_ARGS+=(--env-file "${WORKDIR}/.env")
  fi

  exec docker run --rm \
    -v "$WORKDIR:/work" \
    -w /work \
    "${DOCKER_ENV_ARGS[@]}" \
    -e HOME=/tmp \
    -e USER=hermes \
    -e TOOLCHAIN_QUIET="$TOOLCHAIN_QUIET" \
    -e CODEX_CMD="$CMD" \
    -e STRICT_FLAKE_RUNNER="$STRICT_FLAKE_RUNNER" \
    nixos/nix:2.24.14 \
    sh -lc 'if [ "${TOOLCHAIN_QUIET:-0}" = "1" ]; then NQ="--quiet"; else NQ=""; fi; nix --extra-experimental-features "nix-command flakes" develop $NQ --impure --command bash -lc "$STRICT_FLAKE_RUNNER"'
fi

echo "Neither nix nor docker is available. Install one of them to continue." >&2
exit 1
