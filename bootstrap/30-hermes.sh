#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "ERROR: must run as root." >&2
  exit 1
fi

if [[ ! -r /etc/os-release ]]; then
  echo "ERROR: /etc/os-release missing; cannot validate distribution." >&2
  exit 1
fi

# shellcheck disable=SC1091
source /etc/os-release
if [[ "${ID:-}" != "debian" || "${VERSION_ID:-}" != "12" ]]; then
  echo "ERROR: unsupported OS. Expected Debian 12, got ${ID:-unknown} ${VERSION_ID:-unknown}." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

for bin in useradd install systemctl pipx jq sha256sum; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "ERROR: required command not found: $bin" >&2
    exit 1
  fi
done

install_if_changed() {
  local src="$1"
  local dst="$2"
  local mode="$3"
  local owner="$4"
  local group="$5"

  local tmp
  tmp="$(mktemp)"
  cp "$src" "$tmp"

  if [[ -f "$dst" ]] && cmp -s "$tmp" "$dst"; then
    rm -f "$tmp"
    return 1
  fi

  install -o "$owner" -g "$group" -m "$mode" "$tmp" "$dst"
  rm -f "$tmp"
  return 0
}

if ! id -u hermes >/dev/null 2>&1; then
  useradd --system --create-home --home-dir /var/lib/hermes --shell /usr/sbin/nologin hermes
fi

install -d -m 0750 -o root -g root /etc/hermes
install -d -m 0750 -o hermes -g hermes /var/lib/hermes

if [[ ! -f /etc/hermes/hermes.env ]]; then
  install -m 0600 -o root -g root /dev/null /etc/hermes/hermes.env
fi
chmod 0600 /etc/hermes/hermes.env

if ! grep -Eq '^HERMES_API_KEY=.+$' /etc/hermes/hermes.env; then
  echo "ERROR: /etc/hermes/hermes.env must contain non-empty HERMES_API_KEY." >&2
  exit 1
fi

: "${HERMES_AGENT_VERSION:?HERMES_AGENT_VERSION must be set (pin required for production)}"
if ! [[ "${HERMES_AGENT_VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z]+)*$ ]]; then
  echo "ERROR: HERMES_AGENT_VERSION must be a pinned semantic version (example: 1.5.2)." >&2
  exit 1
fi

pkg_changed=0
current_version="$(PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin pipx list --json 2>/dev/null | jq -r '.venvs["hermes-agent"].metadata.main_package.package_version // empty')"
if [[ "$current_version" != "$HERMES_AGENT_VERSION" ]]; then
  PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin \
    pipx install --force "hermes-agent==${HERMES_AGENT_VERSION}"
  pkg_changed=1
fi

env_changed=0
ENV_STATE_FILE="/var/lib/hermes/.env.sha256"
ENV_SUM="$(sha256sum /etc/hermes/hermes.env | awk '{print $1}')"
if [[ ! -f "$ENV_STATE_FILE" ]] || [[ "$(cat "$ENV_STATE_FILE")" != "$ENV_SUM" ]]; then
  printf '%s\n' "$ENV_SUM" > "$ENV_STATE_FILE"
  chown root:hermes "$ENV_STATE_FILE"
  chmod 0640 "$ENV_STATE_FILE"
  env_changed=1
fi

svc_changed=0
if install_if_changed "$ROOT_DIR/templates/systemd/hermes.service" "/etc/systemd/system/hermes.service" 0644 root root; then
  svc_changed=1
fi

systemctl daemon-reload
systemctl enable hermes.service
if [[ "$svc_changed" -eq 1 || "$pkg_changed" -eq 1 || "$env_changed" -eq 1 ]]; then
  systemctl restart hermes.service
elif ! systemctl is-active --quiet hermes.service; then
  systemctl start hermes.service
fi
