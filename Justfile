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
# Legacy compatibility glue for non-migrated log/audit recipes only.
# Migrated operational workflows below delegate provider and preflight validation
# through hermes_vps_app.just_shim into hermes_vps_app.cli.
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
init PROVIDER_ARG="":
    @./scripts/toolchain.sh "python3 -m hermes_vps_app.just_shim init --repo-root . --provider '{{ PROVIDER }}' --provider-arg '{{ PROVIDER_ARG }}'"

# Initialize OpenTofu and upgrade provider/module plugins
init-upgrade PROVIDER_ARG="":
    @./scripts/toolchain.sh "python3 -m hermes_vps_app.just_shim init-upgrade --repo-root . --provider '{{ PROVIDER }}' --provider-arg '{{ PROVIDER_ARG }}'"

# Create and save OpenTofu execution plan (tofuplan)
plan PROVIDER_ARG="":
    @./scripts/toolchain.sh "python3 -m hermes_vps_app.just_shim plan --repo-root . --provider '{{ PROVIDER }}' --provider-arg '{{ PROVIDER_ARG }}'"

# Apply tofuplan (regenerates plan automatically when stale/missing)
apply PROVIDER_ARG="":
    @./scripts/toolchain.sh "python3 -m hermes_vps_app.just_shim apply --repo-root . --provider '{{ PROVIDER }}' --provider-arg '{{ PROVIDER_ARG }}'"

# Destroy managed infrastructure (requires CONFIRM=YES)
destroy CONFIRM="NO" PROVIDER_ARG="":
    @./scripts/toolchain.sh "python3 -m hermes_vps_app.just_shim destroy --repo-root . --provider '{{ PROVIDER }}' --provider-arg '{{ PROVIDER_ARG }}' --confirm '{{ CONFIRM }}'"

# Compatibility alias for destroy
down CONFIRM="NO" PROVIDER_ARG="":
    @just destroy CONFIRM={{ CONFIRM }} PROVIDER_ARG={{ PROVIDER_ARG }}

# Run post-provision bootstrap scripts over SSH
bootstrap PROVIDER_ARG="":
    @./scripts/toolchain.sh "python3 -m hermes_vps_app.just_shim bootstrap --repo-root . --provider '{{ PROVIDER }}' --provider-arg '{{ PROVIDER_ARG }}'"
# Run remote verification checks on the provisioned server
verify PROVIDER_ARG="":
    @./scripts/toolchain.sh "python3 -m hermes_vps_app.just_shim verify --repo-root . --provider '{{ PROVIDER }}' --provider-arg '{{ PROVIDER_ARG }}'"

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
up PROVIDER_ARG="":
    @./scripts/toolchain.sh "python3 -m hermes_vps_app.just_shim up --repo-root . --provider '{{ PROVIDER }}' --provider-arg '{{ PROVIDER_ARG }}'"

# Comprehensive deployment pipeline: infra + bootstrap + validation + hardening checks
deploy PROVIDER_ARG="":
    @./scripts/toolchain.sh "python3 -m hermes_vps_app.just_shim deploy --repo-root . --provider '{{ PROVIDER }}' --provider-arg '{{ PROVIDER_ARG }}'"
