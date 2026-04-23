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
if [[ "${ID:-}" != "debian" || "${VERSION_ID:-}" != "13" ]]; then
  echo "ERROR: unsupported OS. Expected Debian 13, got ${ID:-unknown} ${VERSION_ID:-unknown}." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

for bin in sshd nft systemctl jq fail2ban-client; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "ERROR: required command not found: $bin" >&2
    exit 1
  fi
done

NFT_RENDERED="$(mktemp)"
SSHD_CANDIDATE="$(mktemp)"
trap 'rm -f "$NFT_RENDERED" "$SSHD_CANDIDATE"' EXIT

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

if ! getent group sshadmins >/dev/null 2>&1; then
  groupadd --system sshadmins
fi

if [[ -n "${SUDO_USER:-}" ]] && id -u "$SUDO_USER" >/dev/null 2>&1; then
  usermod -aG sshadmins "$SUDO_USER"
fi

# Validate candidate SSH config before replacing live config.
cp "$ROOT_DIR/templates/ssh/sshd_config" "$SSHD_CANDIDATE"
sshd -t -f "$SSHD_CANDIDATE"

ssh_changed=0
if install_if_changed "$SSHD_CANDIDATE" "/etc/ssh/sshd_config" 0644 root root; then
  ssh_changed=1
fi

if [[ "$ssh_changed" -eq 1 ]]; then
  if ! systemctl reload ssh; then
    systemctl restart ssh
  fi
fi

install_if_changed "$ROOT_DIR/templates/sysctl/99-hardening.conf" "/etc/sysctl.d/99-hardening.conf" 0644 root root || true
sysctl --system >/dev/null

# Deterministic nftables render using strict JSON validation.
RAW_ALLOWED_TCP_PORTS="${TF_VAR_allowed_tcp_ports:-[]}"
if ! jq -e '
  type == "array" and
  all(
    .[];
    type == "number" and . == floor and . >= 1 and . <= 65535
  ) and
  (length == (map(tostring) | unique | length))
' >/dev/null <<< "$RAW_ALLOWED_TCP_PORTS"; then
  echo "ERROR: TF_VAR_allowed_tcp_ports must be a JSON array of unique integer TCP ports in range 1-65535." >&2
  exit 1
fi

declare -A ALLOWED_PORT_SET=()
ALLOWED_PORT_SET["22"]=1
while IFS= read -r port; do
  [[ -z "$port" || "$port" == "22" ]] && continue
  ALLOWED_PORT_SET["$port"]=1
done < <(jq -r '.[] | tostring' <<< "$RAW_ALLOWED_TCP_PORTS")

mapfile -t ALLOWED_PORTS_SORTED < <(printf '%s\n' "${!ALLOWED_PORT_SET[@]}" | sort -n)
PORTS_CSV="$(IFS=', '; echo "${ALLOWED_PORTS_SORTED[*]}")"

cat > "$NFT_RENDERED" <<EOF
#!/usr/sbin/nft -f
# Managed by bootstrap/20-hardening.sh - do not edit manually.
flush ruleset

table inet filter {
  set allowed_tcp_ports {
    type inet_service
    elements = { ${PORTS_CSV} }
  }

  chain input {
    type filter hook input priority 0; policy drop;

    iif "lo" accept
    ct state established,related accept
    ct state invalid drop

    ip protocol icmp accept
    ip6 nexthdr icmpv6 accept

    tcp dport @allowed_tcp_ports ct state new accept

    counter drop
  }

  chain forward {
    type filter hook forward priority 0; policy drop;
  }

  chain output {
    type filter hook output priority 0; policy accept;
  }
}
EOF

nft -c -f "$NFT_RENDERED"
install_if_changed "$NFT_RENDERED" /etc/nftables.conf 0644 root root || true

# Apply explicit rules before enabling service.
nft -f /etc/nftables.conf
systemctl enable --now nftables

f2b_changed=0
if install_if_changed "$ROOT_DIR/templates/fail2ban/fail2ban.local" "/etc/fail2ban/fail2ban.local" 0644 root root; then
  f2b_changed=1
fi

if install_if_changed "$ROOT_DIR/templates/fail2ban/jail.local" "/etc/fail2ban/jail.local" 0644 root root; then
  f2b_changed=1
fi

fail2ban-client -t >/dev/null
systemctl enable --now fail2ban
if [[ "$f2b_changed" -eq 1 ]]; then
  systemctl restart fail2ban
fi

# Remove legacy journal logrotate policy from older revisions.
if [[ -f /etc/logrotate.d/journal ]]; then
  rm -f /etc/logrotate.d/journal
fi
