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

echo "[verify] sshd syntax"
sshd -t

echo "[verify] ssh effective settings"
SSHD_EFFECTIVE="$(sshd -T)"
for expected in \
  "permitrootlogin no" \
  "passwordauthentication no" \
  "kbdinteractiveauthentication no" \
  "pubkeyauthentication yes" \
  "authenticationmethods publickey" \
  "allowgroups sshadmins"; do
  if ! grep -Fqx "$expected" <<< "$SSHD_EFFECTIVE"; then
    echo "ERROR: expected sshd setting missing: $expected" >&2
    exit 1
  fi
done

echo "[verify] nftables active"
systemctl is-active --quiet nftables
nft list ruleset >/dev/null

echo "[verify] fail2ban active"
systemctl is-active --quiet fail2ban
fail2ban-client ping >/dev/null
fail2ban-client status sshd >/dev/null
fail2ban-client status recidive >/dev/null

echo "[verify] time sync"
systemctl is-active --quiet systemd-timesyncd
timedatectl show -p NTPSynchronized --value | grep -q true

echo "[verify] unattended upgrades"
systemctl is-enabled --quiet unattended-upgrades

echo "[verify] journald persistence"
grep -q '^Storage=persistent' /etc/systemd/journald.conf

echo "[verify] sysctl loaded"
sysctl -n net.ipv4.tcp_syncookies | grep -q '^1$'
sysctl -n net.ipv4.conf.all.accept_redirects | grep -q '^0$'
sysctl -n kernel.unprivileged_bpf_disabled | grep -q '^1$'

echo "[verify] service status"
systemctl is-enabled --quiet hermes
systemctl is-enabled --quiet telegram-gateway
systemctl is-active --quiet hermes
systemctl is-active --quiet telegram-gateway

echo "[verify] systemd hardening flags"
for unit in hermes telegram-gateway; do
  [[ "$(systemctl show -p NoNewPrivileges --value "${unit}.service")" == "yes" ]]
  [[ "$(systemctl show -p ProtectSystem --value "${unit}.service")" == "full" ]]
  [[ "$(systemctl show -p ProtectHome --value "${unit}.service")" == "yes" ]]
  [[ "$(systemctl show -p PrivateTmp --value "${unit}.service")" == "yes" ]]
  [[ "$(systemctl show -p PrivateDevices --value "${unit}.service")" == "yes" ]]
  [[ "$(systemctl show -p RestrictSUIDSGID --value "${unit}.service")" == "yes" ]]
done

echo "[verify] permissions"
stat -c '%a %U %G' /etc/hermes/hermes.env | grep -q '^600 root root$'
stat -c '%a %U %G' /etc/telegram-gateway/gateway.env | grep -q '^600 root root$'

echo "[verify] telegram allowlist fail-closed inputs"
grep -Eq '^TELEGRAM_BOT_TOKEN=.+$' /etc/telegram-gateway/gateway.env
grep -Eq '^TELEGRAM_ALLOWLIST_IDS=-?[0-9]+(,-?[0-9]+)*$' /etc/telegram-gateway/gateway.env

echo "All verification checks passed. Keep your current SSH session open and test a new SSH session before closing this one."
