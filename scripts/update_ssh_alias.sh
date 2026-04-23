#!/usr/bin/env bash
set -euo pipefail

CONFIG_PATH="${1:-.ssh/config}"
HOST_ALIAS="${2:-hermes-vps}"
HOSTNAME_VALUE="${3:-}"

if [[ -z "${HOSTNAME_VALUE}" ]]; then
  echo "ERROR: hostname/IP value required" >&2
  exit 1
fi

CONFIG_DIR="$(dirname "${CONFIG_PATH}")"
mkdir -p "${CONFIG_DIR}"
touch "${CONFIG_PATH}"
chmod 600 "${CONFIG_PATH}"

python3 - "${CONFIG_PATH}" "${HOST_ALIAS}" "${HOSTNAME_VALUE}" <<'PY'
from pathlib import Path
import re
import sys

config_path = Path(sys.argv[1])
host_alias = sys.argv[2]
hostname_value = sys.argv[3]

lines = config_path.read_text(encoding="utf-8").splitlines(keepends=True)

host_re = re.compile(r"^\s*Host\s+(.+?)\s*$", re.IGNORECASE)
hostname_re = re.compile(r"^\s*HostName\s+", re.IGNORECASE)

block_start = None
block_end = None
for i, line in enumerate(lines):
    m = host_re.match(line)
    if not m:
        continue
    aliases = m.group(1).split()
    if host_alias in aliases:
        block_start = i
        j = i + 1
        while j < len(lines) and not host_re.match(lines[j]):
            j += 1
        block_end = j
        break

if block_start is None:
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    if lines and lines[-1].strip() != "":
        lines.append("\n")
    lines.extend([
        f"Host {host_alias}\n",
        f"  HostName {hostname_value}\n",
    ])
else:
    replaced = False
    for k in range(block_start + 1, block_end):
        if hostname_re.match(lines[k]):
            lines[k] = f"  HostName {hostname_value}\n"
            replaced = True
            break
    if not replaced:
        lines.insert(block_start + 1, f"  HostName {hostname_value}\n")

config_path.write_text("".join(lines), encoding="utf-8")
PY

echo "Updated ${CONFIG_PATH}: Host ${HOST_ALIAS} -> HostName ${HOSTNAME_VALUE}"