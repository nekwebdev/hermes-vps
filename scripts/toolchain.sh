#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 '<command>'" >&2
  exit 64
fi

CMD="$1"
WORKDIR="$(pwd)"

if command -v nix >/dev/null 2>&1; then
  exec nix --extra-experimental-features 'nix-command flakes' develop --impure "path:${WORKDIR}" --command bash -lc "$CMD"
fi

if command -v docker >/dev/null 2>&1; then
  exec docker run --rm \
    -v "$WORKDIR:/work" \
    -w /work \
    -e HOME=/tmp \
    -e USER=hermes \
    -e CODEX_CMD="$CMD" \
    nixos/nix:2.24.14 \
    sh -lc 'nix --extra-experimental-features "nix-command flakes" develop --impure --command bash -lc "$CODEX_CMD"'
fi

echo "Neither nix nor docker is available. Install one of them to continue." >&2
exit 1
