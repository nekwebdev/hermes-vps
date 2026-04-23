set shell := ["bash", "-c"]
set dotenv-load := true
set quiet := true

# Default provider. Override with either:
#   just PROVIDER=linode plan
# or (make-style ergonomics):
#   just plan PROVIDER=linode
PROVIDER := "hetzner"

@default:
  @printf '%s\n' \
    'hermes-vps Just targets' \
    '' \
    'Core:' \
    '  just init [PROVIDER=linode]' \
    '  just init-upgrade [PROVIDER=linode]' \
    '  just plan [PROVIDER=linode]' \
    '  just apply [PROVIDER=linode]' \
    '  just destroy CONFIRM=YES [PROVIDER=linode]' \
    '  just bootstrap [PROVIDER=linode]' \
    '  just verify [PROVIDER=linode]' \
    '  just logs [PROVIDER=linode] [SERVICE=all|hermes|telegram-gateway|ssh|fail2ban|nftables]' \
    '  just hardening-audit [PROVIDER=linode]' \
    '' \
    'Aliases:' \
    '  just up [PROVIDER=linode]                    # apply' \
    '  just down CONFIRM=YES [PROVIDER=linode]     # destroy' \
    '  just check [PROVIDER=linode]                 # verify' \
    '  just audit [PROVIDER=linode]                 # hardening-audit' \
    '' \
    'Example flows:' \
    '  first run: just init && just plan' \
    '  deploy:    just apply && just bootstrap' \
    '  verify:    just verify && just hardening-audit' \
    '  teardown:  just destroy CONFIRM=YES'

@_preflight PROVIDER_ARG="":
  @set -euo pipefail; \
  P='{{PROVIDER}}'; \
  if [[ -n '{{PROVIDER_ARG}}' ]]; then \
    if [[ '{{PROVIDER_ARG}}' =~ ^PROVIDER=(hetzner|linode)$ ]]; then \
      P='{{PROVIDER_ARG}}'; \
      P="${P#PROVIDER=}"; \
    else \
      echo "ERROR: invalid provider override '{{PROVIDER_ARG}}'. Use PROVIDER=hetzner or PROVIDER=linode."; \
      exit 1; \
    fi; \
  fi; \
  if [[ ! -f .env ]]; then \
    echo "ERROR: .env is missing. Fix: cp .env.example .env && chmod 600 .env && edit values."; \
    exit 1; \
  fi; \
  ENV_MODE="$(stat -c '%a' .env)"; \
  if (( (8#${ENV_MODE}) & 077 )); then \
    echo "ERROR: .env permissions are too broad (${ENV_MODE}). Fix: chmod 600 .env"; \
    exit 1; \
  fi; \
  if [[ "$P" != 'hetzner' && "$P" != 'linode' ]]; then \
    echo "ERROR: provider must be hetzner or linode."; \
    exit 1; \
  fi; \
  TF_DIR="opentofu/providers/${P}"; \
  if [[ ! -d "$TF_DIR" ]]; then \
    echo "ERROR: OpenTofu provider directory not found: ${TF_DIR}"; \
    exit 1; \
  fi

init PROVIDER_ARG="": (_preflight PROVIDER_ARG)
  @set -euo pipefail; \
  P='{{PROVIDER}}'; \
  if [[ -n '{{PROVIDER_ARG}}' ]]; then P='{{PROVIDER_ARG}}'; P="${P#PROVIDER=}"; fi; \
  TF_DIR="opentofu/providers/${P}"; \
  ./scripts/toolchain.sh "TF_VAR_cloud_provider=${P} tofu -chdir=${TF_DIR} init"

init-upgrade PROVIDER_ARG="": (_preflight PROVIDER_ARG)
  @set -euo pipefail; \
  P='{{PROVIDER}}'; \
  if [[ -n '{{PROVIDER_ARG}}' ]]; then P='{{PROVIDER_ARG}}'; P="${P#PROVIDER=}"; fi; \
  TF_DIR="opentofu/providers/${P}"; \
  ./scripts/toolchain.sh "TF_VAR_cloud_provider=${P} tofu -chdir=${TF_DIR} init -upgrade"

plan PROVIDER_ARG="": (_preflight PROVIDER_ARG)
  @set -euo pipefail; \
  P='{{PROVIDER}}'; \
  if [[ -n '{{PROVIDER_ARG}}' ]]; then P='{{PROVIDER_ARG}}'; P="${P#PROVIDER=}"; fi; \
  TF_DIR="opentofu/providers/${P}"; \
  ./scripts/toolchain.sh "TF_VAR_cloud_provider=${P} tofu -chdir=${TF_DIR} plan -out=tofuplan"

apply PROVIDER_ARG="": (_preflight PROVIDER_ARG)
  @set -euo pipefail; \
  P='{{PROVIDER}}'; \
  if [[ -n '{{PROVIDER_ARG}}' ]]; then P='{{PROVIDER_ARG}}'; P="${P#PROVIDER=}"; fi; \
  TF_DIR="opentofu/providers/${P}"; \
  ./scripts/toolchain.sh "TF_VAR_cloud_provider=${P} tofu -chdir=${TF_DIR} apply tofuplan"

destroy CONFIRM="NO" PROVIDER_ARG="": (_preflight PROVIDER_ARG)
  @set -euo pipefail; \
  C='{{CONFIRM}}'; \
  if [[ "$C" == CONFIRM=* ]]; then C="${C#CONFIRM=}"; fi; \
  if [[ "$C" != 'YES' ]]; then \
    echo 'WARNING: destroy is destructive and cannot be undone.'; \
    echo 'Refusing to continue. Re-run with: just destroy CONFIRM=YES [PROVIDER=linode]'; \
    exit 1; \
  fi; \
  P='{{PROVIDER}}'; \
  if [[ -n '{{PROVIDER_ARG}}' ]]; then P='{{PROVIDER_ARG}}'; P="${P#PROVIDER=}"; fi; \
  TF_DIR="opentofu/providers/${P}"; \
  umask 077; \
  BACKUP_ROOT='.state-backups'; \
  BACKUP_DIR="${BACKUP_ROOT}/${P}"; \
  TS="$(date -u +%Y%m%dT%H%M%SZ)"; \
  BACKUP_FILE="${BACKUP_DIR}/tfstate-${TS}.tar.gz"; \
  mkdir -p "${BACKUP_DIR}"; \
  chmod 700 "${BACKUP_ROOT}" "${BACKUP_DIR}"; \
  mapfile -t STATE_FILES < <(find "${TF_DIR}" -type f \( -name '*.tfstate' -o -name '*.tfstate.backup' \)); \
  if (( ${#STATE_FILES[@]} > 0 )); then \
    tar -czf "${BACKUP_FILE}" "${STATE_FILES[@]}"; \
    chmod 600 "${BACKUP_FILE}"; \
    echo "Saved local state backup: ${BACKUP_FILE}"; \
  else \
    echo "No local state files found under ${TF_DIR}; skipping backup archive."; \
  fi; \
  ./scripts/toolchain.sh "TF_VAR_cloud_provider=${P} tofu -chdir=${TF_DIR} destroy"

bootstrap PROVIDER_ARG="": (_preflight PROVIDER_ARG)
  @set -euo pipefail; \
  P='{{PROVIDER}}'; \
  if [[ -n '{{PROVIDER_ARG}}' ]]; then P='{{PROVIDER_ARG}}'; P="${P#PROVIDER=}"; fi; \
  TF_DIR="opentofu/providers/${P}"; \
  SERVER_IP=$(./scripts/toolchain.sh "TF_VAR_cloud_provider=${P} tofu -chdir=${TF_DIR} output -raw public_ipv4"); \
  ADMIN_USER=$(./scripts/toolchain.sh "TF_VAR_cloud_provider=${P} tofu -chdir=${TF_DIR} output -raw admin_username"); \
  SSH_PORT="${BOOTSTRAP_SSH_PORT:-22}"; \
  KEY_PATH_RAW="${BOOTSTRAP_SSH_PRIVATE_KEY_PATH:-}"; \
  KEY_PATH="${KEY_PATH_RAW/#\~/$HOME}"; \
  if [[ -z "${KEY_PATH}" ]]; then \
    echo "ERROR: BOOTSTRAP_SSH_PRIVATE_KEY_PATH is required in .env"; \
    exit 1; \
  fi; \
  if [[ ! -f "${KEY_PATH}" ]]; then \
    echo "ERROR: SSH private key not found: ${KEY_PATH}"; \
    exit 1; \
  fi; \
  if [[ ! -r "${KEY_PATH}" ]]; then \
    echo "ERROR: SSH private key is not readable: ${KEY_PATH}"; \
    exit 1; \
  fi; \
  KEY_MODE="$(stat -c '%a' "${KEY_PATH}")"; \
  if (( (8#${KEY_MODE}) & 077 )); then \
    echo "ERROR: SSH private key permissions are too broad (${KEY_MODE}). Fix: chmod 600 ${KEY_PATH}"; \
    exit 1; \
  fi; \
  : "${HERMES_API_KEY:?ERROR: HERMES_API_KEY must be set in .env}"; \
  : "${HERMES_AGENT_VERSION:?ERROR: HERMES_AGENT_VERSION must be set in .env}"; \
  : "${TELEGRAM_BOT_TOKEN:?ERROR: TELEGRAM_BOT_TOKEN must be set in .env}"; \
  : "${TELEGRAM_ALLOWLIST_IDS:?ERROR: TELEGRAM_ALLOWLIST_IDS must be set in .env}"; \
  RAW_ALLOWED_PORTS="${TF_VAR_allowed_tcp_ports:-[]}"; \
  if [[ "${RAW_ALLOWED_PORTS}" =~ [\"\'\\\`\$] ]]; then \
    echo "ERROR: TF_VAR_allowed_tcp_ports contains unsupported characters. Use numeric JSON array syntax like [443,8443]."; \
    exit 1; \
  fi; \
  if ! [[ "${HERMES_AGENT_VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z]+)*$ ]]; then \
    echo "ERROR: HERMES_AGENT_VERSION must be a pinned semantic version (example: 1.5.2)."; \
    exit 1; \
  fi; \
  if ! [[ "${TELEGRAM_ALLOWLIST_IDS}" =~ ^-?[0-9]+(,-?[0-9]+)*$ ]]; then \
    echo "ERROR: TELEGRAM_ALLOWLIST_IDS must be comma-separated integers (example: 12345,-100987654321)."; \
    exit 1; \
  fi; \
  cleanup_runtime() { \
    if command -v shred >/dev/null 2>&1; then \
      shred -u bootstrap/runtime/hermes.env bootstrap/runtime/telegram-gateway.env 2>/dev/null || true; \
    fi; \
    rm -f bootstrap/runtime/hermes.env bootstrap/runtime/telegram-gateway.env; \
    rmdir bootstrap/runtime 2>/dev/null || true; \
  }; \
  trap cleanup_runtime EXIT; \
  mkdir -p bootstrap/runtime; \
  umask 077; \
  printf '%s\n' \
    "HERMES_MODEL=${TF_VAR_hermes_model:-anthropic/claude-sonnet-4}" \
    "HERMES_PROVIDER=${TF_VAR_hermes_provider:-openrouter}" \
    "HERMES_API_KEY=${HERMES_API_KEY:-}" \
    "HERMES_AGENT_VERSION=${HERMES_AGENT_VERSION:-}" \
    > bootstrap/runtime/hermes.env; \
  umask 077; \
  printf '%s\n' \
    "TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN:-}" \
    "TELEGRAM_ALLOWLIST_IDS=${TELEGRAM_ALLOWLIST_IDS:-}" \
    "TELEGRAM_POLL_TIMEOUT=${TELEGRAM_POLL_TIMEOUT:-30}" \
    "HERMES_COMMAND=/usr/local/bin/hermes" \
    "HERMES_SYSTEM_PROMPT=You are Hermes Agent running on a personal production VPS." \
    > bootstrap/runtime/telegram-gateway.env; \
  ssh -i "${KEY_PATH}" -p "${SSH_PORT}" -o StrictHostKeyChecking=accept-new "${ADMIN_USER}@${SERVER_IP}" \
    'sudo install -d -m 0700 -o root -g root /root/hermes-vps-stage'; \
  rsync -az --delete --rsync-path="sudo rsync" --chmod=D0700,F0600 \
    -e "ssh -i ${KEY_PATH} -p ${SSH_PORT} -o StrictHostKeyChecking=accept-new" \
    bootstrap/ templates/ "${ADMIN_USER}@${SERVER_IP}:/root/hermes-vps-stage/"; \
  ssh -i "${KEY_PATH}" -p "${SSH_PORT}" -o StrictHostKeyChecking=accept-new "${ADMIN_USER}@${SERVER_IP}" \
    "sudo bash -c 'set -euo pipefail; \
      install -d -m 0750 /etc/hermes /etc/telegram-gateway; \
      install -m 0600 -o root -g root /root/hermes-vps-stage/bootstrap/runtime/hermes.env /etc/hermes/hermes.env; \
      install -m 0600 -o root -g root /root/hermes-vps-stage/bootstrap/runtime/telegram-gateway.env /etc/telegram-gateway/gateway.env; \
      bash /root/hermes-vps-stage/bootstrap/10-base.sh; \
      TF_VAR_allowed_tcp_ports=\"${RAW_ALLOWED_PORTS}\" bash /root/hermes-vps-stage/bootstrap/20-hardening.sh; \
      HERMES_AGENT_VERSION=\"${HERMES_AGENT_VERSION}\" bash /root/hermes-vps-stage/bootstrap/30-hermes.sh; \
      bash /root/hermes-vps-stage/bootstrap/40-telegram-gateway.sh; \
      bash /root/hermes-vps-stage/bootstrap/90-verify.sh; \
      find /root/hermes-vps-stage/bootstrap/runtime -maxdepth 1 -type f -name \"*.env\" -exec shred -u {} + 2>/dev/null || true; \
      rm -rf /root/hermes-vps-stage/bootstrap/runtime'"
verify PROVIDER_ARG="": (_preflight PROVIDER_ARG)
  @set -euo pipefail; \
  P='{{PROVIDER}}'; \
  if [[ -n '{{PROVIDER_ARG}}' ]]; then P='{{PROVIDER_ARG}}'; P="${P#PROVIDER=}"; fi; \
  TF_DIR="opentofu/providers/${P}"; \
  SERVER_IP=$(./scripts/toolchain.sh "TF_VAR_cloud_provider=${P} tofu -chdir=${TF_DIR} output -raw public_ipv4"); \
  ADMIN_USER=$(./scripts/toolchain.sh "TF_VAR_cloud_provider=${P} tofu -chdir=${TF_DIR} output -raw admin_username"); \
  SSH_PORT="${BOOTSTRAP_SSH_PORT:-22}"; \
  KEY_PATH_RAW="${BOOTSTRAP_SSH_PRIVATE_KEY_PATH:-}"; \
  KEY_PATH="${KEY_PATH_RAW/#\~/$HOME}"; \
  if [[ -z "${KEY_PATH}" || ! -f "${KEY_PATH}" || ! -r "${KEY_PATH}" ]]; then \
    echo "ERROR: readable BOOTSTRAP_SSH_PRIVATE_KEY_PATH is required."; \
    exit 1; \
  fi; \
  KEY_MODE="$(stat -c '%a' "${KEY_PATH}")"; \
  if (( (8#${KEY_MODE}) & 077 )); then \
    echo "ERROR: SSH private key permissions are too broad (${KEY_MODE}). Fix: chmod 600 ${KEY_PATH}"; \
    exit 1; \
  fi; \
  ssh -i "${KEY_PATH}" -p "${SSH_PORT}" -o StrictHostKeyChecking=accept-new "${ADMIN_USER}@${SERVER_IP}" "sudo bash /root/hermes-vps-stage/bootstrap/90-verify.sh"

logs SERVICE="all" PROVIDER_ARG="": (_preflight PROVIDER_ARG)
  @set -euo pipefail; \
  P='{{PROVIDER}}'; \
  if [[ -n '{{PROVIDER_ARG}}' ]]; then P='{{PROVIDER_ARG}}'; P="${P#PROVIDER=}"; fi; \
  TF_DIR="opentofu/providers/${P}"; \
  SERVER_IP=$(./scripts/toolchain.sh "TF_VAR_cloud_provider=${P} tofu -chdir=${TF_DIR} output -raw public_ipv4"); \
  ADMIN_USER=$(./scripts/toolchain.sh "TF_VAR_cloud_provider=${P} tofu -chdir=${TF_DIR} output -raw admin_username"); \
  SSH_PORT="${BOOTSTRAP_SSH_PORT:-22}"; \
  KEY_PATH_RAW="${BOOTSTRAP_SSH_PRIVATE_KEY_PATH:-}"; \
  KEY_PATH="${KEY_PATH_RAW/#\~/$HOME}"; \
  SVC='{{SERVICE}}'; \
  if [[ "$SVC" == SERVICE=* ]]; then SVC="${SVC#SERVICE=}"; fi; \
  if [[ -z "${KEY_PATH}" || ! -f "${KEY_PATH}" || ! -r "${KEY_PATH}" ]]; then \
    echo "ERROR: readable BOOTSTRAP_SSH_PRIVATE_KEY_PATH is required."; \
    exit 1; \
  fi; \
  KEY_MODE="$(stat -c '%a' "${KEY_PATH}")"; \
  if (( (8#${KEY_MODE}) & 077 )); then \
    echo "ERROR: SSH private key permissions are too broad (${KEY_MODE}). Fix: chmod 600 ${KEY_PATH}"; \
    exit 1; \
  fi; \
  if [[ "$SVC" != 'all' && "$SVC" != 'hermes' && "$SVC" != 'telegram-gateway' && "$SVC" != 'ssh' && "$SVC" != 'fail2ban' && "$SVC" != 'nftables' ]]; then \
    echo "ERROR: invalid SERVICE '${SVC}'. Allowed: all|hermes|telegram-gateway|ssh|fail2ban|nftables"; \
    exit 1; \
  fi; \
  if [[ "$SVC" == 'all' ]]; then \
    ssh -i "${KEY_PATH}" -p "${SSH_PORT}" -o StrictHostKeyChecking=accept-new "${ADMIN_USER}@${SERVER_IP}" \
      "sudo journalctl -u ssh -u fail2ban -u nftables -u hermes -u telegram-gateway --no-pager -n 200"; \
  else \
    ssh -i "${KEY_PATH}" -p "${SSH_PORT}" -o StrictHostKeyChecking=accept-new "${ADMIN_USER}@${SERVER_IP}" \
      "sudo journalctl -u ${SVC} --no-pager -n 200"; \
  fi

hardening-audit PROVIDER_ARG="": (_preflight PROVIDER_ARG)
  @set -euo pipefail; \
  P='{{PROVIDER}}'; \
  if [[ -n '{{PROVIDER_ARG}}' ]]; then P='{{PROVIDER_ARG}}'; P="${P#PROVIDER=}"; fi; \
  TF_DIR="opentofu/providers/${P}"; \
  SERVER_IP=$(./scripts/toolchain.sh "TF_VAR_cloud_provider=${P} tofu -chdir=${TF_DIR} output -raw public_ipv4"); \
  ADMIN_USER=$(./scripts/toolchain.sh "TF_VAR_cloud_provider=${P} tofu -chdir=${TF_DIR} output -raw admin_username"); \
  SSH_PORT="${BOOTSTRAP_SSH_PORT:-22}"; \
  KEY_PATH_RAW="${BOOTSTRAP_SSH_PRIVATE_KEY_PATH:-}"; \
  KEY_PATH="${KEY_PATH_RAW/#\~/$HOME}"; \
  if [[ -z "${KEY_PATH}" || ! -f "${KEY_PATH}" || ! -r "${KEY_PATH}" ]]; then \
    echo "ERROR: readable BOOTSTRAP_SSH_PRIVATE_KEY_PATH is required."; \
    exit 1; \
  fi; \
  KEY_MODE="$(stat -c '%a' "${KEY_PATH}")"; \
  if (( (8#${KEY_MODE}) & 077 )); then \
    echo "ERROR: SSH private key permissions are too broad (${KEY_MODE}). Fix: chmod 600 ${KEY_PATH}"; \
    exit 1; \
  fi; \
  ssh -i "${KEY_PATH}" -p "${SSH_PORT}" -o StrictHostKeyChecking=accept-new "${ADMIN_USER}@${SERVER_IP}" \
    "sudo sshd -t && sudo nft list ruleset && sudo fail2ban-client status && sudo sysctl -n net.ipv4.tcp_syncookies >/dev/null"

up PROVIDER_ARG="":
  @set -euo pipefail; \
  just apply '{{PROVIDER_ARG}}' PROVIDER='{{PROVIDER}}'

check PROVIDER_ARG="":
  @set -euo pipefail; \
  just verify '{{PROVIDER_ARG}}' PROVIDER='{{PROVIDER}}'

audit PROVIDER_ARG="":
  @set -euo pipefail; \
  just hardening-audit '{{PROVIDER_ARG}}' PROVIDER='{{PROVIDER}}'

down CONFIRM="NO" PROVIDER_ARG="":
  @set -euo pipefail; \
  just destroy CONFIRM='{{CONFIRM}}' '{{PROVIDER_ARG}}' PROVIDER='{{PROVIDER}}'
