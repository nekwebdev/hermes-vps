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

for bin in useradd install systemctl sha256sum; do
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

if ! id -u tg-gateway >/dev/null 2>&1; then
  useradd --system --create-home --home-dir /var/lib/telegram-gateway --shell /usr/sbin/nologin tg-gateway
fi

install -d -m 0750 -o root -g root /etc/telegram-gateway
install -d -m 0750 -o tg-gateway -g tg-gateway /opt/telegram-gateway
install -d -m 0750 -o tg-gateway -g tg-gateway /var/lib/telegram-gateway
install -d -m 0700 -o tg-gateway -g tg-gateway /var/lib/telegram-gateway/.hermes

if [[ -s /var/lib/hermes/.hermes/auth.json ]]; then
  install -m 0600 -o tg-gateway -g tg-gateway /var/lib/hermes/.hermes/auth.json /var/lib/telegram-gateway/.hermes/auth.json
fi

if [[ ! -f /etc/telegram-gateway/gateway.env ]]; then
  install -m 0600 -o root -g root /dev/null /etc/telegram-gateway/gateway.env
fi
chmod 0600 /etc/telegram-gateway/gateway.env

if ! grep -Eq '^TELEGRAM_BOT_TOKEN=.+$' /etc/telegram-gateway/gateway.env; then
  echo "ERROR: /etc/telegram-gateway/gateway.env must contain non-empty TELEGRAM_BOT_TOKEN." >&2
  exit 1
fi

if ! grep -Eq '^TELEGRAM_ALLOWLIST_IDS=-?[0-9]+(,-?[0-9]+)*$' /etc/telegram-gateway/gateway.env; then
  echo "ERROR: TELEGRAM_ALLOWLIST_IDS must be a comma-separated list of integer IDs." >&2
  exit 1
fi

if ! dpkg -s python3-requests >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends python3-requests
fi

GATEWAY_TMP="$(mktemp)"
cat > "$GATEWAY_TMP" <<'PYEOF'
#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys
import time
from typing import Set

import requests


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


def parse_allowlist(raw: str) -> Set[int]:
    values = set()
    for part in raw.split(","):
        p = part.strip()
        if not p:
            continue
        if not re.fullmatch(r"-?\d+", p):
            raise RuntimeError(f"invalid TELEGRAM_ALLOWLIST_IDS element: {p!r}")
        values.add(int(p))
    if not values:
        raise RuntimeError("TELEGRAM_ALLOWLIST_IDS is empty")
    return values


TOKEN = required_env("TELEGRAM_BOT_TOKEN")
ALLOWLIST = parse_allowlist(required_env("TELEGRAM_ALLOWLIST_IDS"))
POLL_TIMEOUT = int(os.getenv("TELEGRAM_POLL_TIMEOUT", "30"))
HERMES_COMMAND = os.getenv("HERMES_COMMAND", "/usr/local/bin/hermes")
SYSTEM_PROMPT = os.getenv("HERMES_SYSTEM_PROMPT", "You are Hermes Agent.")
if POLL_TIMEOUT < 1 or POLL_TIMEOUT > 120:
    raise RuntimeError("TELEGRAM_POLL_TIMEOUT must be between 1 and 120 seconds")

BASE = f"https://api.telegram.org/bot{TOKEN}"
SESSION = requests.Session()


def telegram(method: str, payload: dict) -> dict:
    response = SESSION.post(f"{BASE}/{method}", json=payload, timeout=(10, POLL_TIMEOUT + 10))
    response.raise_for_status()
    body = response.json()
    if not body.get("ok"):
        raise RuntimeError(f"telegram api error: {body}")
    return body


def send_message(chat_id: int, text: str) -> None:
    telegram("sendMessage", {"chat_id": chat_id, "text": text[:3500]})


def run_hermes(user_text: str) -> str:
    prompt = f"{SYSTEM_PROMPT}\n\nUser message: {user_text}"
    provider = os.getenv("HERMES_PROVIDER", "auto").strip() or "auto"
    model = os.getenv("HERMES_MODEL", "").strip()

    cmd = [HERMES_COMMAND, "chat", "-Q", "--provider", provider]
    if model:
        cmd.extend(["-m", model])
    cmd.extend(["-q", prompt])

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        detail = stderr or stdout or f"exit code {proc.returncode}"
        return f"Hermes command failed: {detail[:700]}"
    output = proc.stdout.strip()
    return output or "(empty response)"


def main() -> None:
    offset = 0
    while True:
        try:
            result = telegram(
                "getUpdates",
                {"timeout": POLL_TIMEOUT, "offset": offset, "allowed_updates": ["message"]},
            )
            updates = result.get("result", [])
            for update in updates:
                offset = update["update_id"] + 1
                message = update.get("message", {})
                chat = message.get("chat", {})
                chat_id = int(chat.get("id", 0))
                user = message.get("from", {})
                user_id = int(user.get("id", 0))
                text = message.get("text", "").strip()

                if not text:
                    continue

                if chat_id not in ALLOWLIST and user_id not in ALLOWLIST:
                    print(
                        json.dumps({"event": "deny", "chat_id": chat_id, "user_id": user_id}),
                        file=sys.stderr,
                        flush=True,
                    )
                    continue

                reply = run_hermes(text)
                send_message(chat_id, reply)
        except Exception as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr, flush=True)
            time.sleep(3)


if __name__ == "__main__":
    main()
PYEOF

py_changed=0
if install_if_changed "$GATEWAY_TMP" /opt/telegram-gateway/gateway.py 0750 root tg-gateway; then
  py_changed=1
fi
rm -f "$GATEWAY_TMP"

env_changed=0
ENV_STATE_FILE="/var/lib/telegram-gateway/.env.sha256"
ENV_SUM="$(sha256sum /etc/telegram-gateway/gateway.env | awk '{print $1}')"
if [[ ! -f "$ENV_STATE_FILE" ]] || [[ "$(cat "$ENV_STATE_FILE")" != "$ENV_SUM" ]]; then
  printf '%s\n' "$ENV_SUM" > "$ENV_STATE_FILE"
  chown root:tg-gateway "$ENV_STATE_FILE"
  chmod 0640 "$ENV_STATE_FILE"
  env_changed=1
fi

svc_changed=0
if install_if_changed "$ROOT_DIR/templates/systemd/telegram-gateway.service" "/etc/systemd/system/telegram-gateway.service" 0644 root root; then
  svc_changed=1
fi

HERMES_PROVIDER_VALUE="$(awk -F= '/^HERMES_PROVIDER=/{print $2; exit}' /etc/hermes/hermes.env)"
HERMES_PROVIDER_VALUE="${HERMES_PROVIDER_VALUE:-openrouter}"
HERMES_MODEL_VALUE="$(awk -F= '/^HERMES_MODEL=/{print $2; exit}' /etc/hermes/hermes.env)"
HERMES_MODEL_VALUE="${HERMES_MODEL_VALUE:-anthropic/claude-sonnet-4}"

sudo -u tg-gateway env HERMES_HOME=/var/lib/telegram-gateway/.hermes \
  /usr/local/bin/hermes config set model.provider "$HERMES_PROVIDER_VALUE" >/dev/null
sudo -u tg-gateway env HERMES_HOME=/var/lib/telegram-gateway/.hermes \
  /usr/local/bin/hermes config set model.default "$HERMES_MODEL_VALUE" >/dev/null

systemctl daemon-reload
systemctl enable telegram-gateway.service
if [[ "$svc_changed" -eq 1 || "$py_changed" -eq 1 || "$env_changed" -eq 1 ]]; then
  systemctl restart telegram-gateway.service
elif ! systemctl is-active --quiet telegram-gateway.service; then
  systemctl start telegram-gateway.service
fi
