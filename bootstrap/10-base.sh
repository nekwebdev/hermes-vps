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

export DEBIAN_FRONTEND=noninteractive

APT_PACKAGES=(
  ca-certificates
  curl
  jq
  rsync
  nftables
  fail2ban
  unattended-upgrades
  apt-listchanges
  systemd-timesyncd
  logrotate
  python3
  python3-pip
  pipx
  sudo
)

need_update=0
for pkg in "${APT_PACKAGES[@]}"; do
  if ! dpkg -s "$pkg" >/dev/null 2>&1; then
    need_update=1
    break
  fi
done

if [[ "$need_update" -eq 1 ]]; then
  apt-get update
  apt-get install -y --no-install-recommends "${APT_PACKAGES[@]}"
fi

if [[ ! -d /var/log/journal ]]; then
  install -d -m 2755 /var/log/journal
fi

restart_journald=0
if grep -q '^#\?Storage=' /etc/systemd/journald.conf; then
  sed -ri 's|^#?Storage=.*$|Storage=persistent|' /etc/systemd/journald.conf
  restart_journald=1
elif ! grep -q '^Storage=' /etc/systemd/journald.conf; then
  printf '%s\n' 'Storage=persistent' >> /etc/systemd/journald.conf
  restart_journald=1
fi

systemctl enable --now systemd-timesyncd
if [[ "$restart_journald" -eq 1 ]]; then
  systemctl restart systemd-journald
fi

cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF

systemctl enable --now unattended-upgrades
