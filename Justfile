set shell := ["bash", "-c"]
set dotenv-load := true
set quiet := true

# Provider source of truth is .env (TF_VAR_cloud_provider).
# Optional override forms:
#   just PROVIDER=linode plan
#   just plan PROVIDER=linode

PROVIDER := env("TF_VAR_cloud_provider", "")

# Show recipe list with descriptions
@default:
    @just --list
# Validate provider selection, .env safety, and provider directory prerequisites
@_preflight PROVIDER_ARG="":
    @set -euo pipefail; \
    P='{{ PROVIDER }}'; \
    if [[ -z "$P" ]]; then P="${TF_VAR_cloud_provider:-}"; fi; \
    if [[ -n '{{ PROVIDER_ARG }}' ]]; then \
      if [[ '{{ PROVIDER_ARG }}' =~ ^PROVIDER=(hetzner|linode)$ ]]; then \
        P='{{ PROVIDER_ARG }}'; \
        P="${P#PROVIDER=}"; \
      else \
        echo "ERROR: invalid provider override '{{ PROVIDER_ARG }}'. Use PROVIDER=hetzner or PROVIDER=linode."; \
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

# Interactive onboarding: cloud, server, Hermes, Telegram, and optional SSH alias
configure:
    @set -euo pipefail; \
    TOOLCHAIN_QUIET=1 ./scripts/toolchain.sh "python3 -m scripts.configure_tui"

# Initialize OpenTofu in the selected provider directory
init PROVIDER_ARG="": (_preflight PROVIDER_ARG)
    @set -euo pipefail; \
    P='{{ PROVIDER }}'; \
    if [[ -z "$P" ]]; then P="${TF_VAR_cloud_provider:-}"; fi; \
    if [[ -n '{{ PROVIDER_ARG }}' ]]; then P='{{ PROVIDER_ARG }}'; P="${P#PROVIDER=}"; fi; \
    ./scripts/toolchain.sh "python3 -m hermes_vps_app.cli init --repo-root . --provider ${P}"

# Initialize OpenTofu and upgrade provider/module plugins
init-upgrade PROVIDER_ARG="": (_preflight PROVIDER_ARG)
    @set -euo pipefail; \
    P='{{ PROVIDER }}'; \
    if [[ -z "$P" ]]; then P="${TF_VAR_cloud_provider:-}"; fi; \
    if [[ -n '{{ PROVIDER_ARG }}' ]]; then P='{{ PROVIDER_ARG }}'; P="${P#PROVIDER=}"; fi; \
    ./scripts/toolchain.sh "python3 -m hermes_vps_app.cli init-upgrade --repo-root . --provider ${P}"

# Create and save OpenTofu execution plan (tofuplan)
plan PROVIDER_ARG="": (_preflight PROVIDER_ARG)
    @set -euo pipefail; \
    P='{{ PROVIDER }}'; \
    if [[ -z "$P" ]]; then P="${TF_VAR_cloud_provider:-}"; fi; \
    if [[ -n '{{ PROVIDER_ARG }}' ]]; then P='{{ PROVIDER_ARG }}'; P="${P#PROVIDER=}"; fi; \
    ./scripts/toolchain.sh "python3 -m hermes_vps_app.cli plan --repo-root . --provider ${P}"

# Apply tofuplan (regenerates plan automatically when stale/missing)
apply PROVIDER_ARG="": (_preflight PROVIDER_ARG)
    @set -euo pipefail; \
    P='{{ PROVIDER }}'; \
    if [[ -z "$P" ]]; then P="${TF_VAR_cloud_provider:-}"; fi; \
    if [[ -n '{{ PROVIDER_ARG }}' ]]; then P='{{ PROVIDER_ARG }}'; P="${P#PROVIDER=}"; fi; \
    ./scripts/toolchain.sh "python3 -m hermes_vps_app.cli apply --repo-root . --provider ${P}"

# Destroy managed infrastructure (requires CONFIRM=YES)
destroy CONFIRM="NO" PROVIDER_ARG="": (_preflight PROVIDER_ARG)
    @set -euo pipefail; \
    C='{{ CONFIRM }}'; \
    if [[ "$C" == CONFIRM=* ]]; then C="${C#CONFIRM=}"; fi; \
    if [[ "$C" != 'YES' ]]; then \
      echo 'WARNING: destroy is destructive and cannot be undone.'; \
      echo 'Refusing to continue. Re-run with: just destroy CONFIRM=YES [PROVIDER=linode]'; \
      exit 1; \
    fi; \
    P='{{ PROVIDER }}'; \
    if [[ -z "$P" ]]; then P="${TF_VAR_cloud_provider:-}"; fi; \
    if [[ -n '{{ PROVIDER_ARG }}' ]]; then P='{{ PROVIDER_ARG }}'; P="${P#PROVIDER=}"; fi; \
    ./scripts/toolchain.sh "python3 -m hermes_vps_app.cli destroy --repo-root . --provider ${P} --approve-destructive DESTROY:${P}"

# Compatibility alias for destroy
down CONFIRM="NO" PROVIDER_ARG="":
    @just destroy CONFIRM={{ CONFIRM }} PROVIDER_ARG={{ PROVIDER_ARG }}

# Run post-provision bootstrap scripts over SSH
bootstrap PROVIDER_ARG="": (_preflight PROVIDER_ARG)
    @set -euo pipefail; \
    P='{{ PROVIDER }}'; \
    if [[ -z "$P" ]]; then P="${TF_VAR_cloud_provider:-}"; fi; \
    if [[ -n '{{ PROVIDER_ARG }}' ]]; then P='{{ PROVIDER_ARG }}'; P="${P#PROVIDER=}"; fi; \
    ./scripts/toolchain.sh "python3 -m hermes_vps_app.cli bootstrap --repo-root . --provider ${P}"
# Run remote verification checks on the provisioned server
verify PROVIDER_ARG="": (_preflight PROVIDER_ARG)
    @set -euo pipefail; \
    P='{{ PROVIDER }}'; \
    if [[ -z "$P" ]]; then P="${TF_VAR_cloud_provider:-}"; fi; \
    if [[ -n '{{ PROVIDER_ARG }}' ]]; then P='{{ PROVIDER_ARG }}'; P="${P#PROVIDER=}"; fi; \
    ./scripts/toolchain.sh "python3 -m hermes_vps_app.cli verify --repo-root . --provider ${P}"

# Show recent journal logs from one service or all core services
logs SERVICE="all" PROVIDER_ARG="": (_preflight PROVIDER_ARG)
    @set -euo pipefail; \
    P='{{ PROVIDER }}'; \
    if [[ -z "$P" ]]; then P="${TF_VAR_cloud_provider:-}"; fi; \
    if [[ -n '{{ PROVIDER_ARG }}' ]]; then P='{{ PROVIDER_ARG }}'; P="${P#PROVIDER=}"; fi; \
    TF_DIR="opentofu/providers/${P}"; \
    SERVER_IP=$(./scripts/toolchain.sh "TF_VAR_cloud_provider=${P} tofu -chdir=${TF_DIR} output -raw public_ipv4"); \
    ADMIN_USER=$(./scripts/toolchain.sh "TF_VAR_cloud_provider=${P} tofu -chdir=${TF_DIR} output -raw admin_username"); \
    SSH_PORT="${BOOTSTRAP_SSH_PORT:-22}"; \
    KEY_PATH_RAW="${BOOTSTRAP_SSH_PRIVATE_KEY_PATH:-}"; \
    KEY_PATH="${KEY_PATH_RAW/#\~/$HOME}"; \
    SVC='{{ SERVICE }}'; \
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

# Run security hardening audit commands over SSH
hardening-audit PROVIDER_ARG="": (_preflight PROVIDER_ARG)
    @set -euo pipefail; \
    P='{{ PROVIDER }}'; \
    if [[ -z "$P" ]]; then P="${TF_VAR_cloud_provider:-}"; fi; \
    if [[ -n '{{ PROVIDER_ARG }}' ]]; then P='{{ PROVIDER_ARG }}'; P="${P#PROVIDER=}"; fi; \
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

# Convenience alias: init + plan + apply
up PROVIDER_ARG="": (_preflight PROVIDER_ARG)
    @set -euo pipefail; \
    P='{{ PROVIDER }}'; \
    if [[ -z "$P" ]]; then P="${TF_VAR_cloud_provider:-}"; fi; \
    if [[ -n '{{ PROVIDER_ARG }}' ]]; then P='{{ PROVIDER_ARG }}'; P="${P#PROVIDER=}"; fi; \
    ./scripts/toolchain.sh "python3 -m hermes_vps_app.cli up --repo-root . --provider ${P}"

# Comprehensive deployment pipeline: infra + bootstrap + validation + hardening checks
deploy PROVIDER_ARG="": (_preflight PROVIDER_ARG)
    @set -euo pipefail; \
    P='{{ PROVIDER }}'; \
    if [[ -z "$P" ]]; then P="${TF_VAR_cloud_provider:-}"; fi; \
    if [[ -n '{{ PROVIDER_ARG }}' ]]; then P='{{ PROVIDER_ARG }}'; P="${P#PROVIDER=}"; fi; \
    ./scripts/toolchain.sh "python3 -m hermes_vps_app.cli deploy --repo-root . --provider ${P}"
