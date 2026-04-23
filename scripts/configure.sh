#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_TEMPLATE="${ROOT_DIR}/.env.example"
ENV_FILE="${ROOT_DIR}/.env"
RUNTIME_DIR="${ROOT_DIR}/bootstrap/runtime"
HERMES_AUTH_HOME="${RUNTIME_DIR}/hermes-home"
HERMES_AUTH_ARTIFACT="${RUNTIME_DIR}/hermes-auth.json"

for bin in gum jq python3; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "ERROR: required command not found: $bin" >&2
    exit 1
  fi
done

set_env_value() {
  local key="$1"
  local value="$2"

  python3 - "$ENV_FILE" "$key" "$value" <<'PY'
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
key = sys.argv[2]
value = sys.argv[3]
line = f"{key}={value}"

content = path.read_text()
pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
if pattern.search(content):
    content = pattern.sub(line, content, count=1)
else:
    if content and not content.endswith("\n"):
        content += "\n"
    content += line + "\n"
path.write_text(content)
PY
}

get_env_value() {
  local key="$1"
  python3 - "$ENV_FILE" "$key" <<'PY'
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
key = sys.argv[2]
content = path.read_text()
match = re.search(rf"^{re.escape(key)}=(.*)$", content, re.MULTILINE)
if match:
    print(match.group(1))
PY
}

server_image_for_provider() {
  local provider="$1"
  case "$provider" in
    linode) printf '%s\n' "linode/debian13" ;;
    hetzner) printf '%s\n' "debian-13" ;;
    *)
      echo "ERROR: unsupported provider for server image mapping: ${provider}" >&2
      exit 1
      ;;
  esac
}

contains_exact() {
  local needle="$1"
  shift
  local item
  for item in "$@"; do
    if [[ "$item" == "$needle" ]]; then
      return 0
    fi
  done
  return 1
}

run_with_spinner() {
  local title="$1"
  shift

  if [[ -t 2 ]]; then
    gum spin --spinner dot --title "$title" --show-output -- "$@"
  else
    "$@"
  fi
}

CONFIGURE_ALT_ACTIVE="0"

enter_alt_screen() {
  if [[ "${CONFIGURE_ALT_SCREEN:-0}" != "1" ]]; then
    return 0
  fi
  printf '\033[?1049h'
  CONFIGURE_ALT_ACTIVE="1"
}

exit_alt_screen() {
  if [[ "${CONFIGURE_ALT_ACTIVE}" == "1" ]]; then
    printf '\033[?1049l'
    CONFIGURE_ALT_ACTIVE="0"
  fi
}

clear_screen() {
  if [[ "${CONFIGURE_ALT_ACTIVE}" == "1" ]]; then
    printf '\033[2J\033[H'
  fi
}

render_step_box() {
  local step="$1"
  local s1='Step 1: Cloud'
  local s2='Step 2: Server'
  local s3='Step 3: Hermes'
  local s4='Step 4: Telegram'

  if [[ "$step" == "1" ]]; then
    s1="$(gum style --foreground 10 --bold "$s1")"
    s2="$(gum style --foreground 245 "$s2")"
    s3="$(gum style --foreground 245 "$s3")"
    s4="$(gum style --foreground 245 "$s4")"
  elif [[ "$step" == "2" ]]; then
    s1="$(gum style --foreground 245 "$s1")"
    s2="$(gum style --foreground 10 --bold "$s2")"
    s3="$(gum style --foreground 245 "$s3")"
    s4="$(gum style --foreground 245 "$s4")"
  elif [[ "$step" == "3" ]]; then
    s1="$(gum style --foreground 245 "$s1")"
    s2="$(gum style --foreground 245 "$s2")"
    s3="$(gum style --foreground 10 --bold "$s3")"
    s4="$(gum style --foreground 245 "$s4")"
  else
    s1="$(gum style --foreground 245 "$s1")"
    s2="$(gum style --foreground 245 "$s2")"
    s3="$(gum style --foreground 245 "$s3")"
    s4="$(gum style --foreground 10 --bold "$s4")"
  fi

  local title
  title="$(gum style --bold 'hermes-vps configuration')"
  gum style --border rounded --padding "1 2" --margin "1 0" "$(gum join --vertical \
    "$title" \
    "$s1" \
    "$s2" \
    "$s3" \
    "$s4")"
}

render_done_box() {
  local title
  title="$(gum style --bold 'hermes-vps configuration')"
  gum style --border rounded --padding "1 2" --margin "1 0" "$(gum join --vertical \
    "$title")"
}

print_provider_token_setup() {
  local provider="$1"

  if [[ "$provider" == "hetzner" ]]; then
    gum style --bold --foreground 12 "Hetzner token setup"
    gum style "1) Open https://console.hetzner.cloud/"
    gum style "2) Select your project"
    gum style "3) Security -> API Tokens"
    gum style "4) Generate API token with Read & Write scope"
    gum style "5) Paste token"
  else
    gum style --bold --foreground 12 "Linode token setup"
    gum style "1) Open https://cloud.linode.com/profile/tokens"
    gum style "2) Create a Personal Access Token"
    gum style "3) Give Read/Write scope for Linodes"
    gum style "4) Set expiration per your policy"
    gum style "5) Paste token"
  fi
}

print_telegram_token_setup() {
  gum style --bold --foreground 99 "Telegram token setup"
  gum style "1) Open https://web.telegram.org/k/#@BotFather and chat with @BotFather"
  gum style "2) Run /newbot and follow prompts"
  gum style "3) Copy bot token from BotFather"
  gum style "4) Start chat with your bot and send one message"
}

print_telegram_user_id_setup() {
  gum style --bold --foreground 99 "Telegram user ID setup"
  gum style "1) Open https://web.telegram.org/k/#@userinfobot (or https://web.telegram.org/k/#@RawDataBot)"
  gum style "2) Send any message"
  gum style "3) Copy your numeric user id"
  gum style "4) If using group/topic, add negative chat id too"
}

prompt_env_with_default() {
  local key="$1"
  local label="$2"

  local existing
  existing="$(get_env_value "$key")"

  local value
  if [[ -n "$existing" ]]; then
    value="$(gum input --header "$label" --header.foreground 99 --placeholder "${existing}")"
    if [[ -z "$value" ]]; then
      value="$existing"
    fi
  else
    value="$(gum input --header "$label" --header.foreground 99 --placeholder "Enter value")"
  fi

  if [[ -z "$value" ]]; then
    echo "ERROR: ${key} cannot be empty." >&2
    exit 1
  fi

  set_env_value "$key" "$value"
  printf '%s %s\n' \
    "$(gum style --foreground 10 "${label}:")" \
    "$(gum style --foreground 14 "$value")"
}

ensure_ssh_key_material() {
  local key_path="${HOME}/.ssh/hermes-vps"
  local pub_path="${key_path}.pub"

  local created_new="0"
  if [[ -f "$key_path" && -f "$pub_path" ]]; then
    :
  else
    command -v ssh-keygen >/dev/null 2>&1 || { echo "ERROR: ssh-keygen not found." >&2; exit 1; }
    mkdir -p "${HOME}/.ssh"
    chmod 700 "${HOME}/.ssh"
    rm -f "$key_path" "$pub_path"
    ssh-keygen -t ed25519 -f "$key_path" -N "" -C "hermes-vps" >/dev/null 2>&1
    created_new="1"
  fi

  chmod 600 "$key_path"
  chmod 644 "$pub_path"

  local pub_value
  pub_value="$(tr -d '\n' < "$pub_path")"
  if [[ -z "$pub_value" ]]; then
    echo "ERROR: SSH public key is empty: ${pub_path}" >&2
    exit 1
  fi

  set_env_value "BOOTSTRAP_SSH_PRIVATE_KEY_PATH" "$key_path"
  set_env_value "TF_VAR_admin_ssh_public_key" "\"${pub_value}\""

  if [[ "$created_new" == "1" ]]; then
    printf '%s %s\n' \
      "$(gum style --foreground 10 'Created new SSH key:')" \
      "$(gum style --foreground 14 "${key_path}")"
  else
    printf '%s %s\n' \
      "$(gum style --foreground 10 'SSH key:')" \
      "$(gum style --foreground 14 "${key_path}")"
  fi
}

ensure_repo_ssh_alias() {
  local alias_user="$1"
  local alias_key_path="$2"
  local alias_port="$3"
  local selected_hostname="$4"

  local repo_ssh_dir="${ROOT_DIR}/.ssh"
  local repo_ssh_config="${repo_ssh_dir}/config"
  local home_ssh_dir="${HOME}/.ssh"
  local home_ssh_config="${home_ssh_dir}/config"
  local include_line="Include ${repo_ssh_config}"
  local alias_hostname="${selected_hostname}"

  if [[ -z "${alias_hostname}" || "${alias_hostname}" != *.* ]]; then
    alias_hostname="REPLACE_WITH_PUBLIC_IP"
  fi

  mkdir -p "${repo_ssh_dir}" "${home_ssh_dir}"
  chmod 700 "${home_ssh_dir}"

  touch "${home_ssh_config}" "${repo_ssh_config}"
  chmod 600 "${home_ssh_config}" "${repo_ssh_config}"

  if ! grep -Fqx "${include_line}" "${home_ssh_config}"; then
    printf '\n%s\n' "${include_line}" >> "${home_ssh_config}"
  fi

  if grep -Eq '^[[:space:]]*Host[[:space:]]+hermes-vps([[:space:]]|$)' "${repo_ssh_config}"; then
    return 1
  fi

  {
    printf '\nHost hermes-vps\n'
    printf '  HostName %s\n' "${alias_hostname}"
    printf '  User %s\n' "${alias_user}"
    printf '  Port %s\n' "${alias_port}"
    printf '  IdentityFile %s\n' "${alias_key_path}"
    printf '  IdentitiesOnly yes\n'
  } >> "${repo_ssh_config}"

  return 0
}

select_with_preselect() {
  local header="$1"
  local existing="$2"
  shift 2
  local -a options=("$@")

  if (( ${#options[@]} == 0 )); then
    echo "ERROR: no options available for ${header}" >&2
    exit 1
  fi

  local -a ordered_options=("${options[@]}")
  if [[ -n "$existing" ]] && contains_exact "$existing" "${options[@]}"; then
    local selected_index="-1"
    local idx
    for idx in "${!options[@]}"; do
      if [[ "${options[$idx]}" == "$existing" ]]; then
        selected_index="$idx"
        break
      fi
    done

    if (( selected_index >= 0 )); then
      ordered_options=(
        "${options[@]:selected_index}"
        "${options[@]:0:selected_index}"
      )
    fi
  fi

  gum choose --height 20 --header "$header" "${ordered_options[@]}"
}

select_from_labeled_pairs() {
  local header="$1"
  local existing_value="$2"
  shift 2
  local -a pairs=("$@")

  if (( ${#pairs[@]} == 0 )); then
    echo "ERROR: no options available for ${header}" >&2
    exit 1
  fi

  local -a labels=()
  local pair label value selected_label=""
  for pair in "${pairs[@]}"; do
    label="${pair%%$'\t'*}"
    value="${pair#*$'\t'}"
    labels+=("$label")
    if [[ "$value" == "$existing_value" ]]; then
      selected_label="$label"
    fi
  done

  if [[ -n "$selected_label" ]]; then
    local selected_index="-1"
    local idx
    for idx in "${!labels[@]}"; do
      if [[ "${labels[$idx]}" == "$selected_label" ]]; then
        selected_index="$idx"
        break
      fi
    done

    if (( selected_index >= 0 )); then
      local -a ordered_labels=(
        "${labels[@]:selected_index}"
        "${labels[@]:0:selected_index}"
      )
      selected_label="$(gum choose --height 20 --header "$header" "${ordered_labels[@]}")"
    else
      selected_label="$(gum choose --height 20 --header "$header" "${labels[@]}")"
    fi
  else
    selected_label="$(gum choose --height 20 --header "$header" "${labels[@]}")"
  fi

  for pair in "${pairs[@]}"; do
    label="${pair%%$'\t'*}"
    value="${pair#*$'\t'}"
    if [[ "$label" == "$selected_label" ]]; then
      printf '%s\n' "$value"
      return 0
    fi
  done

  echo "ERROR: failed to map selected label back to value for ${header}" >&2
  exit 1
}

label_for_value_from_pairs() {
  local needle_value="$1"
  shift
  local -a pairs=("$@")

  local pair label value
  for pair in "${pairs[@]}"; do
    label="${pair%%$'\t'*}"
    value="${pair#*$'\t'}"
    if [[ "$value" == "$needle_value" ]]; then
      printf '%s\n' "$label"
      return 0
    fi
  done

  return 1
}

fetch_location_pairs() {
  local provider="$1"

  if [[ "$provider" == "hetzner" ]]; then
    command -v hcloud >/dev/null 2>&1 || { echo "ERROR: hcloud CLI not found in toolchain." >&2; exit 1; }
    [[ -n "${HCLOUD_TOKEN:-}" && "${HCLOUD_TOKEN}" != "***" ]] || { echo "ERROR: HCLOUD_TOKEN missing/placeholder in .env" >&2; exit 1; }
    run_with_spinner "Looking up regions..." hcloud location list -o json \
      | jq -r '.[] | "\(.country | ascii_upcase), \(.city) (\(.name))\t\(.name)"' \
      | sort -u
  else
    command -v linode-cli >/dev/null 2>&1 || { echo "ERROR: linode-cli not found in toolchain." >&2; exit 1; }
    [[ -n "${LINODE_TOKEN:-}" && "${LINODE_TOKEN}" != "***" ]] || { echo "ERROR: LINODE_TOKEN missing/placeholder in .env" >&2; exit 1; }
    run_with_spinner "Looking up regions..." env LINODE_CLI_TOKEN="***" linode-cli regions list --json --no-defaults --suppress-warnings \
      | jq -r '.[] | "\(.country | ascii_upcase), \(.label) (\(.id))\t\(.id)"' \
      | sort -u
  fi
}

fetch_server_type_pairs() {
  local provider="$1"
  local location="$2"

  if [[ "$provider" == "hetzner" ]]; then
    command -v hcloud >/dev/null 2>&1 || { echo "ERROR: hcloud CLI not found in toolchain." >&2; exit 1; }
    [[ -n "${HCLOUD_TOKEN:-}" && "${HCLOUD_TOKEN}" != "***" ]] || { echo "ERROR: HCLOUD_TOKEN missing/placeholder in .env" >&2; exit 1; }
    run_with_spinner "Looking up server types..." hcloud server-type list -o json | jq -r --arg location "$location" '
      [ .[]
        | select((.deprecated // false) == false)
        | {
            id: .name,
            cores: .cores,
            memory: .memory,
            disk: .disk,
            price: ([ .prices[]?
              | select(.location == $location)
              | .price_monthly.gross, .price_monthly.net
            ] | map(select(. != null) | tonumber) | min)
          }
        | select(.price != null)
        | . + {
            price_fmt: (
              ((.price * 100 | round) / 100) as $n
              | ($n | floor) as $whole
              | ((($n - $whole) * 100) | round) as $frac
              | "\($whole).\(($frac | tostring) | if length == 1 then "0" + . else . end)"
            )
          }
        | . + {
            label: "\(.id) • \(.cores) vCPU • \(.memory) GB RAM • \(.disk) GB disk • $\(.price_fmt)/mo"
          }
      ] as $rows
      | if ($rows | length) == 0 then
          empty
        else
          ($rows | min_by(.price).id) as $min_id
          | $rows
          | sort_by(.label | ascii_downcase)
          | .[]
          | "\(.label)\t\(.id)\t\(.price)\t\((.id == $min_id) | tostring)"
        end
    '
  else
    command -v linode-cli >/dev/null 2>&1 || { echo "ERROR: linode-cli not found in toolchain." >&2; exit 1; }
    [[ -n "${LINODE_TOKEN:-}" && "${LINODE_TOKEN}" != "***" ]] || { echo "ERROR: LINODE_TOKEN missing/placeholder in .env" >&2; exit 1; }
    run_with_spinner "Looking up server types..." env LINODE_CLI_TOKEN="***" linode-cli linodes types --json --no-defaults --suppress-warnings | jq -r --arg location "$location" '
      [ .[]
        | select((.deprecated // false) == false)
        | select((.regions? == null) or ((.regions | index($location)) != null))
        | {
            id: .id,
            vcpus: .vcpus,
            memory: .memory,
            disk_gb: (.disk / 1024 | floor),
            price: ((.price.monthly // 999999) | tonumber)
          }
        | . + {
            label: "\(.id) • \(.vcpus) vCPU • \(.memory) MB RAM • \(.disk_gb) GB disk • $\(.price)/mo"
          }
      ] as $rows
      | if ($rows | length) == 0 then
          empty
        else
          ($rows | min_by(.price).id) as $min_id
          | $rows
          | sort_by(.label | ascii_downcase)
          | .[]
          | "\(.label)\t\(.id)\t\(.price)\t\((.id == $min_id) | tostring)"
        end
    '
  fi
}

resolve_bundled_hermes_python() {
  command -v hermes >/dev/null 2>&1 || { echo "ERROR: hermes CLI not found in toolchain." >&2; exit 1; }

  local hermes_bin
  hermes_bin="$(command -v hermes)"
  local hermes_python
  hermes_python="$(awk -F"'" '/^export HERMES_PYTHON=/{print $2; exit}' "$hermes_bin")"

  if [[ -z "$hermes_python" ]]; then
    echo "ERROR: failed to resolve HERMES_PYTHON from ${hermes_bin}" >&2
    exit 1
  fi

  if [[ ! -x "$hermes_python" ]]; then
    echo "ERROR: resolved HERMES_PYTHON is not executable: ${hermes_python}" >&2
    exit 1
  fi

  printf '%s\n' "$hermes_python"
}

resolve_bundled_hermes_agent_version() {
  command -v hermes >/dev/null 2>&1 || { echo "ERROR: hermes CLI not found in toolchain." >&2; exit 1; }
  hermes --version | awk '{for (i=1; i<=NF; i++) if ($i ~ /^v[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z]+)*$/) { sub(/^v/, "", $i); print $i; exit }}'
}

resolve_hermes_python_for_version() {
  local requested_version="$1"
  local bundled_version bundled_python

  bundled_version="$(resolve_bundled_hermes_agent_version 2>/dev/null || true)"
  bundled_python="$(resolve_bundled_hermes_python)"

  if [[ -n "${bundled_version}" && "${bundled_version}" == "${requested_version}" ]]; then
    printf '%s\n' "${bundled_python}"
    return 0
  fi

  install -d -m 0700 "${RUNTIME_DIR}"

  local version_slug
  version_slug="$(printf '%s' "${requested_version}" | tr -c 'A-Za-z0-9._-' '_')"
  local venv_dir="${RUNTIME_DIR}/hermes-agent-${version_slug}"
  local venv_python="${venv_dir}/bin/python3"
  local venv_pip="${venv_dir}/bin/pip"

  if [[ -x "${venv_python}" ]] && "${venv_python}" -c 'import hermes_cli.models' >/dev/null 2>&1; then
    printf '%s\n' "${venv_python}"
    return 0
  fi

  rm -rf "${venv_dir}"
  run_with_spinner "Preparing Hermes Agent ${requested_version} runtime..." python3 -m venv "${venv_dir}"

  local install_ok="0"
  set +e
  run_with_spinner "Installing Hermes Agent ${requested_version}..." \
    "${venv_pip}" --disable-pip-version-check --no-input install --quiet "hermes-agent==${requested_version}"
  install_rc=$?
  if [[ "${install_rc}" -eq 0 ]]; then
    install_ok="1"
  else
    run_with_spinner "Retrying install via hermes_agent package name..." \
      "${venv_pip}" --disable-pip-version-check --no-input install --quiet "hermes_agent==${requested_version}"
    install_rc=$?
    if [[ "${install_rc}" -eq 0 ]]; then
      install_ok="1"
    fi
  fi
  set -e

  if [[ "${install_ok}" == "1" ]] && "${venv_python}" -c 'import hermes_cli.models, hermes_cli.auth' >/dev/null 2>&1; then
    printf '%s\n' "${venv_python}"
    return 0
  fi

  rm -rf "${venv_dir}"
  printf '%s\n' "WARN: unable to resolve Hermes metadata runtime for version ${requested_version}; using bundled runtime metadata instead." >&2
  printf '%s\n' "${bundled_python}"
}

fetch_hermes_provider_ids() {
  local hermes_python="$1"

  run_with_spinner "Looking up Hermes providers..." "$hermes_python" -c $'from hermes_cli.models import list_available_providers\nproviders=list_available_providers()\nids=[]\nfor provider in providers:\n    value = provider.get("id") if isinstance(provider, dict) else getattr(provider, "id", None)\n    if value:\n        ids.append(value)\nfor pid in sorted(set(ids), key=str.lower):\n    print(pid)'
}

fetch_hermes_model_ids() {
  local hermes_python="$1"
  local provider="$2"

  run_with_spinner "Looking up Hermes models..." "$hermes_python" -c $'import sys\nfrom hermes_cli.models import provider_model_ids\nprovider=sys.argv[1]\nseen=set()\nfor model_id in provider_model_ids(provider):\n    if model_id in seen:\n        continue\n    seen.add(model_id)\n    print(model_id)' "$provider"
}

fetch_latest_hermes_agent_version() {
  # Runtime truth for configuration: version installed in sandbox toolchain.
  # We intentionally avoid GitHub release tags (e.g. 2026.4.16) because
  # bootstrap version pin expects package semver like 0.10.0.
  resolve_bundled_hermes_agent_version
}

has_usable_secret_value() {
  local value="$1"
  [[ -n "$value" && "$value" != "***" ]]
}

fetch_hermes_provider_auth_metadata() {
  local hermes_python="$1"
  local provider="$2"

  "$hermes_python" -c $'import sys\nfrom hermes_cli.auth import PROVIDER_REGISTRY\nprovider=sys.argv[1]\npc=PROVIDER_REGISTRY.get(provider)\nif not pc:\n    print("api_key\\t")\n    raise SystemExit(0)\nauth_type=getattr(pc, "auth_type", "api_key") or "api_key"\nenv_vars=getattr(pc, "api_key_env_vars", ()) or ()\nprint(f"{auth_type}\\t{\",\".join(env_vars)}")' "$provider"
}

has_local_hermes_auth_state() {
  local hermes_python="$1"
  local provider="$2"

  "$hermes_python" -c $'import sys\nfrom hermes_cli.auth import get_auth_status\nprovider=sys.argv[1]\nstatus=get_auth_status(provider)\nprint("yes" if bool((status or {}).get("logged_in")) else "no")' "$provider"
}

provider_supports_hermes_oauth_add() {
  local provider="$1"
  [[ "$provider" == "openai-codex" || "$provider" == "nous" ]]
}

prepare_local_hermes_auth_home() {
  install -d -m 0700 "${RUNTIME_DIR}"
  install -d -m 0700 "${HERMES_AUTH_HOME}"
}

stage_local_hermes_auth_artifact() {
  local src="${HERMES_AUTH_HOME}/auth.json"
  if [[ -s "$src" ]]; then
    install -m 0600 "$src" "${HERMES_AUTH_ARTIFACT}"
    return 0
  fi
  return 1
}

clear_local_hermes_auth_artifact() {
  rm -f "${HERMES_AUTH_ARTIFACT}"
}

if [[ ! -f "${ENV_TEMPLATE}" ]]; then
  echo "ERROR: missing env template: ${ENV_TEMPLATE}" >&2
  exit 1
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  cp "${ENV_TEMPLATE}" "${ENV_FILE}"
fi
chmod 600 "${ENV_FILE}" || true

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

trap exit_alt_screen EXIT INT TERM
enter_alt_screen

render_step_box 1

EXISTING_PROVIDER="$(get_env_value TF_VAR_cloud_provider)"
if [[ "${EXISTING_PROVIDER}" == "hetzner" || "${EXISTING_PROVIDER}" == "linode" ]]; then
  PROVIDER="$(gum choose --header "Choose cloud provider" --selected "${EXISTING_PROVIDER}" "hetzner" "linode")"
else
  PROVIDER="$(gum choose --header "Choose cloud provider" "hetzner" "linode")"
fi
set_env_value "TF_VAR_cloud_provider" "${PROVIDER}"
SERVER_IMAGE="$(server_image_for_provider "${PROVIDER}")"
set_env_value "TF_VAR_server_image" "${SERVER_IMAGE}"
printf '%s %s\n' \
  "$(gum style --foreground 10 'Cloud:')" \
  "$(gum style --foreground 14 "${PROVIDER}")"
printf '%s %s\n' \
  "$(gum style --foreground 10 'Server image:')" \
  "$(gum style --foreground 14 "${SERVER_IMAGE}")"

if [[ "${PROVIDER}" == "hetzner" ]]; then
  TOKEN_KEY="HCLOUD_TOKEN"
else
  TOKEN_KEY="LINODE_TOKEN"
fi

EXISTING_TOKEN="$(get_env_value "${TOKEN_KEY}")"
NEEDS_TOKEN="yes"
if [[ -n "${EXISTING_TOKEN}" && "${EXISTING_TOKEN}" != "***" ]]; then
  set +e
  gum confirm --default=false "Existing ${TOKEN_KEY} found in .env. Set a new token?"
  confirm_rc=$?
  set -e

  if [[ "${confirm_rc}" -eq 0 ]]; then
    NEEDS_TOKEN="yes"
  else
    NEEDS_TOKEN="no"
  fi
fi

if [[ "${NEEDS_TOKEN}" == "yes" ]]; then
  print_provider_token_setup "${PROVIDER}"
  TOKEN_VALUE="$(gum input --password --placeholder "Paste ${TOKEN_KEY} value")"
  if [[ -z "${TOKEN_VALUE}" ]]; then
    echo "ERROR: token cannot be empty." >&2
    exit 1
  fi
  set_env_value "${TOKEN_KEY}" "${TOKEN_VALUE}"
  if [[ "${TOKEN_KEY}" == "HCLOUD_TOKEN" ]]; then
    export HCLOUD_TOKEN="${TOKEN_VALUE}"
  else
    export LINODE_TOKEN="${TOKEN_VALUE}"
    export LINODE_CLI_TOKEN="${TOKEN_VALUE}"
  fi
  gum style --foreground 10 "Saved ${TOKEN_KEY} in ${ENV_FILE}."
fi

if [[ "${PROVIDER}" == "linode" && -n "${LINODE_TOKEN:-}" ]]; then
  export LINODE_CLI_TOKEN="${LINODE_TOKEN}"
fi

mapfile -t LOCATION_PAIRS < <(fetch_location_pairs "${PROVIDER}")
EXISTING_LOCATION="$(get_env_value TF_VAR_server_location)"
LOCATION="$(select_from_labeled_pairs "Available regions" "${EXISTING_LOCATION}" "${LOCATION_PAIRS[@]}")"
set_env_value "TF_VAR_server_location" "${LOCATION}"
SELECTED_REGION_LABEL="$(label_for_value_from_pairs "${LOCATION}" "${LOCATION_PAIRS[@]}")"
printf '%s %s\n' \
  "$(gum style --foreground 10 'Region:')" \
  "$(gum style --foreground 14 "${SELECTED_REGION_LABEL}")"

mapfile -t TYPE_TRIPLES < <(fetch_server_type_pairs "${PROVIDER}" "${LOCATION}")
if (( ${#TYPE_TRIPLES[@]} == 0 )); then
  echo "ERROR: no server types returned by provider API for location ${LOCATION}" >&2
  exit 1
fi

TYPE_RECOMMENDED_VALUE=""
TYPE_RECOMMENDED_LABEL=""
declare -a TYPE_PAIRS=()
for triple in "${TYPE_TRIPLES[@]}"; do
  type_label="${triple%%$'\t'*}"
  rest="${triple#*$'\t'}"
  type_value="${rest%%$'\t'*}"
  rest="${rest#*$'\t'}"
  type_is_recommended="${rest#*$'\t'}"

  TYPE_PAIRS+=("${type_label}"$'\t'"${type_value}")
  if [[ "${type_is_recommended}" == "true" ]]; then
    TYPE_RECOMMENDED_VALUE="${type_value}"
    TYPE_RECOMMENDED_LABEL="${type_label}"
  fi
done

if [[ -z "${TYPE_RECOMMENDED_VALUE}" ]]; then
  echo "ERROR: failed to determine recommended server type" >&2
  exit 1
fi

EXISTING_TYPE="$(get_env_value TF_VAR_server_type)"
TYPE_SELECTION_SEED="${TYPE_RECOMMENDED_VALUE}"
if [[ -n "${EXISTING_TYPE}" ]]; then
  TYPE_SELECTION_SEED="${EXISTING_TYPE}"
fi

SERVER_TYPE="$(select_from_labeled_pairs "Available server types (recommended: ${TYPE_RECOMMENDED_LABEL})" "${TYPE_SELECTION_SEED}" "${TYPE_PAIRS[@]}")"
set_env_value "TF_VAR_server_type" "${SERVER_TYPE}"
SELECTED_TYPE_LABEL="$(label_for_value_from_pairs "${SERVER_TYPE}" "${TYPE_PAIRS[@]}")"
printf '%s %s\n' \
  "$(gum style --foreground 10 'Server type:')" \
  "$(gum style --foreground 14 "${SELECTED_TYPE_LABEL}")"

clear_screen
render_step_box 2
prompt_env_with_default "TF_VAR_hostname" "Hostname"
prompt_env_with_default "TF_VAR_admin_username" "Admin username"
prompt_env_with_default "TF_VAR_admin_group" "SSH group"
ensure_ssh_key_material

SELECTED_HOSTNAME="$(get_env_value TF_VAR_hostname)"
SELECTED_ADMIN_USERNAME="$(get_env_value TF_VAR_admin_username)"
SELECTED_ADMIN_GROUP="$(get_env_value TF_VAR_admin_group)"
SELECTED_SSH_KEY_PATH="$(get_env_value BOOTSTRAP_SSH_PRIVATE_KEY_PATH)"

clear_screen
render_step_box 3

LATEST_HERMES_AGENT_VERSION="$(fetch_latest_hermes_agent_version 2>/dev/null || true)"
if ! [[ "${LATEST_HERMES_AGENT_VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z]+)*$ ]]; then
  LATEST_HERMES_AGENT_VERSION="$(resolve_bundled_hermes_agent_version 2>/dev/null || true)"
fi
if ! [[ "${LATEST_HERMES_AGENT_VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z]+)*$ ]]; then
  LATEST_HERMES_AGENT_VERSION="0.10.0"
fi

HERMES_AGENT_VERSION_INPUT="$(gum input --header "Hermes Agent version" --header.foreground 99 --placeholder "${LATEST_HERMES_AGENT_VERSION}")"
if [[ -n "${HERMES_AGENT_VERSION_INPUT}" ]]; then
  HERMES_AGENT_VERSION="${HERMES_AGENT_VERSION_INPUT}"
else
  HERMES_AGENT_VERSION="${LATEST_HERMES_AGENT_VERSION}"
fi

if ! [[ "${HERMES_AGENT_VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z]+)*$ ]]; then
  echo "ERROR: Hermes Agent version must be a pinned semantic version (example: 1.5.2)." >&2
  exit 1
fi

set_env_value "HERMES_AGENT_VERSION" "${HERMES_AGENT_VERSION}"
printf '%s %s\n' \
  "$(gum style --foreground 10 'Hermes Agent version:')" \
  "$(gum style --foreground 14 "${HERMES_AGENT_VERSION}")"

HERMES_PYTHON="$(resolve_hermes_python_for_version "${HERMES_AGENT_VERSION}")"
prepare_local_hermes_auth_home
export HERMES_HOME="${HERMES_AUTH_HOME}"
mapfile -t HERMES_PROVIDER_OPTIONS < <(fetch_hermes_provider_ids "${HERMES_PYTHON}")
if (( ${#HERMES_PROVIDER_OPTIONS[@]} == 0 )); then
  echo "ERROR: no Hermes providers discovered at runtime" >&2
  exit 1
fi

EXISTING_HERMES_PROVIDER="$(get_env_value TF_VAR_hermes_provider)"
HERMES_PROVIDER_SEED=""
if [[ -n "${EXISTING_HERMES_PROVIDER}" ]] && contains_exact "${EXISTING_HERMES_PROVIDER}" "${HERMES_PROVIDER_OPTIONS[@]}"; then
  HERMES_PROVIDER_SEED="${EXISTING_HERMES_PROVIDER}"
elif contains_exact "openai-codex" "${HERMES_PROVIDER_OPTIONS[@]}"; then
  HERMES_PROVIDER_SEED="openai-codex"
else
  HERMES_PROVIDER_SEED="${HERMES_PROVIDER_OPTIONS[0]}"
fi

HERMES_PROVIDER="$(select_with_preselect "Provider" "${HERMES_PROVIDER_SEED}" "${HERMES_PROVIDER_OPTIONS[@]}")"
set_env_value "TF_VAR_hermes_provider" "${HERMES_PROVIDER}"
printf '%s %s\n' \
  "$(gum style --foreground 10 'Provider:')" \
  "$(gum style --foreground 14 "${HERMES_PROVIDER}")"

mapfile -t HERMES_MODEL_OPTIONS < <(fetch_hermes_model_ids "${HERMES_PYTHON}" "${HERMES_PROVIDER}")
if (( ${#HERMES_MODEL_OPTIONS[@]} == 0 )); then
  echo "ERROR: no Hermes models discovered for provider ${HERMES_PROVIDER}" >&2
  exit 1
fi

EXISTING_HERMES_MODEL="$(get_env_value TF_VAR_hermes_model)"
HERMES_MODEL_SEED=""
if [[ -n "${EXISTING_HERMES_MODEL}" ]] && contains_exact "${EXISTING_HERMES_MODEL}" "${HERMES_MODEL_OPTIONS[@]}"; then
  HERMES_MODEL_SEED="${EXISTING_HERMES_MODEL}"
elif [[ "${HERMES_PROVIDER}" == "openai-codex" ]] && contains_exact "gpt-5.4-mini" "${HERMES_MODEL_OPTIONS[@]}"; then
  HERMES_MODEL_SEED="gpt-5.4-mini"
else
  HERMES_MODEL_SEED="${HERMES_MODEL_OPTIONS[0]}"
fi

HERMES_MODEL="$(select_with_preselect "Model (${HERMES_PROVIDER})" "${HERMES_MODEL_SEED}" "${HERMES_MODEL_OPTIONS[@]}")"
set_env_value "TF_VAR_hermes_model" "${HERMES_MODEL}"
printf '%s %s\n' \
  "$(gum style --foreground 10 'Model:')" \
  "$(gum style --foreground 14 "${HERMES_MODEL}")"

HERMES_AUTH_META="$(fetch_hermes_provider_auth_metadata "${HERMES_PYTHON}" "${HERMES_PROVIDER}")"
HERMES_AUTH_TYPE="${HERMES_AUTH_META%%$'\t'*}"
HERMES_AUTH_ENV_VARS_CSV="${HERMES_AUTH_META#*$'\t'}"
if [[ -z "${HERMES_AUTH_TYPE}" ]]; then
  HERMES_AUTH_TYPE="***"
fi

RECAP_HERMES_AUTH_TYPE="${HERMES_AUTH_TYPE}"
RECAP_HERMES_AUTH_ARTIFACT="none"

if [[ "${HERMES_AUTH_TYPE}" == "api_key" ]]; then
  clear_local_hermes_auth_artifact
  HERMES_AUTH_PRESENT="no"
  HERMES_AUTH_SOURCE=""
  HERMES_AUTH_VALUE=""

  EXISTING_HERMES_API_KEY="$(get_env_value HERMES_API_KEY)"
  if has_usable_secret_value "${EXISTING_HERMES_API_KEY}"; then
    HERMES_AUTH_PRESENT="yes"
    HERMES_AUTH_SOURCE="HERMES_API_KEY"
    HERMES_AUTH_VALUE="${EXISTING_HERMES_API_KEY}"
  else
    IFS=',' read -r -a HERMES_AUTH_ENV_VARS <<< "${HERMES_AUTH_ENV_VARS_CSV}"
    for auth_env_var in "${HERMES_AUTH_ENV_VARS[@]}"; do
      [[ -n "${auth_env_var}" ]] || continue
      auth_env_value="$(get_env_value "${auth_env_var}")"
      if has_usable_secret_value "${auth_env_value}"; then
        HERMES_AUTH_PRESENT="yes"
        HERMES_AUTH_SOURCE="${auth_env_var}"
        HERMES_AUTH_VALUE="${auth_env_value}"
        break
      fi
    done
  fi

  if [[ "${HERMES_AUTH_PRESENT}" == "yes" ]]; then
    if [[ "${HERMES_AUTH_SOURCE}" != "HERMES_API_KEY" ]]; then
      set_env_value "HERMES_API_KEY" "${HERMES_AUTH_VALUE}"
      printf '%s %s\n' \
        "$(gum style --foreground 10 'Hermes auth:')" \
        "$(gum style --foreground 14 "API key found in ${HERMES_AUTH_SOURCE} (copied to HERMES_API_KEY)")"
    else
      printf '%s %s\n' \
        "$(gum style --foreground 10 'Hermes auth:')" \
        "$(gum style --foreground 14 "API key found in HERMES_API_KEY")"
    fi
  else
    AUTH_ACTION="$(gum choose --header "Hermes auth (${HERMES_PROVIDER})" "Enter API key now" "Skip for now")"
    if [[ "${AUTH_ACTION}" == "Enter API key now" ]]; then
      NEW_HERMES_API_KEY="$(gum input --password --placeholder "Paste API key for ${HERMES_PROVIDER}")"
      if [[ -z "${NEW_HERMES_API_KEY}" ]]; then
        echo "ERROR: API key cannot be empty." >&2
        exit 1
      fi
      set_env_value "HERMES_API_KEY" "${NEW_HERMES_API_KEY}"

      IFS=',' read -r -a HERMES_AUTH_ENV_VARS <<< "${HERMES_AUTH_ENV_VARS_CSV}"
      if (( ${#HERMES_AUTH_ENV_VARS[@]} > 0 )) && [[ -n "${HERMES_AUTH_ENV_VARS[0]}" ]]; then
        set_env_value "${HERMES_AUTH_ENV_VARS[0]}" "${NEW_HERMES_API_KEY}"
      fi

      printf '%s %s\n' \
        "$(gum style --foreground 10 'Hermes auth:')" \
        "$(gum style --foreground 14 "API key saved")"
    else
      printf '%s %s\n' \
        "$(gum style --foreground 10 'Hermes auth:')" \
        "$(gum style --foreground 14 "Skipped for now")"
    fi
  fi
else
  LOCAL_HERMES_AUTH_PRESENT="$(has_local_hermes_auth_state "${HERMES_PYTHON}" "${HERMES_PROVIDER}" 2>/dev/null || true)"
  if [[ "${LOCAL_HERMES_AUTH_PRESENT}" == "yes" ]]; then
    RENEW_OAUTH_AUTH="no"
    renew_rc=0

    if provider_supports_hermes_oauth_add "${HERMES_PROVIDER}"; then
      set +e
      gum confirm --default=false "Local OAuth auth found for ${HERMES_PROVIDER}. Renew now?"
      renew_choice_rc=$?
      set -e
      if [[ "${renew_choice_rc}" -eq 0 ]]; then
        RENEW_OAUTH_AUTH="yes"
      fi
    fi

    if [[ "${RENEW_OAUTH_AUTH}" == "yes" ]]; then
      set +e
      hermes auth add "${HERMES_PROVIDER}" --type oauth
      renew_rc=$?
      set -e
    fi

    LOCAL_HERMES_AUTH_PRESENT="$(has_local_hermes_auth_state "${HERMES_PYTHON}" "${HERMES_PROVIDER}" 2>/dev/null || true)"
    if [[ "${LOCAL_HERMES_AUTH_PRESENT}" == "yes" ]]; then
      if stage_local_hermes_auth_artifact; then
        RECAP_HERMES_AUTH_ARTIFACT="${HERMES_AUTH_ARTIFACT}"
        printf '%s %s\n' \
          "$(gum style --foreground 10 'Auth artifact:')" \
          "$(gum style --foreground 14 "${HERMES_AUTH_ARTIFACT}")"
      fi
    else
      clear_local_hermes_auth_artifact
      RECAP_HERMES_AUTH_ARTIFACT="none"
    fi

    if [[ "${RENEW_OAUTH_AUTH}" == "yes" ]]; then
      if [[ "${renew_rc}" -eq 0 ]]; then
        printf '%s %s\n' \
          "$(gum style --foreground 10 'Hermes auth:')" \
          "$(gum style --foreground 14 "Auth renewed")"
      elif [[ "${LOCAL_HERMES_AUTH_PRESENT}" == "yes" ]]; then
        printf '%s %s\n' \
          "$(gum style --foreground 10 'Hermes auth:')" \
          "$(gum style --foreground 14 "Renew failed; existing auth kept")"
      else
        printf '%s %s\n' \
          "$(gum style --foreground 10 'Hermes auth:')" \
          "$(gum style --foreground 14 "Renew failed; local auth missing")"
      fi
    else
      printf '%s %s\n' \
        "$(gum style --foreground 10 'Hermes auth:')" \
        "$(gum style --foreground 14 "Local OAuth auth already present for ${HERMES_PROVIDER}")"
    fi
  else
    if provider_supports_hermes_oauth_add "${HERMES_PROVIDER}"; then
      AUTH_ACTION="$(gum choose --header "Hermes auth (${HERMES_PROVIDER})" "Run Hermes auth now" "Skip for now")"
      if [[ "${AUTH_ACTION}" == "Run Hermes auth now" ]]; then
        set +e
        hermes auth add "${HERMES_PROVIDER}" --type oauth
        login_rc=$?
        set -e

        if [[ "${login_rc}" -eq 0 ]]; then
          if stage_local_hermes_auth_artifact; then
            RECAP_HERMES_AUTH_ARTIFACT="${HERMES_AUTH_ARTIFACT}"
            printf '%s %s\n' \
              "$(gum style --foreground 10 'Auth artifact:')" \
              "$(gum style --foreground 14 "${HERMES_AUTH_ARTIFACT}")"
          fi
          printf '%s %s\n' \
            "$(gum style --foreground 10 'Hermes auth:')" \
            "$(gum style --foreground 14 "Login completed")"
        else
          clear_local_hermes_auth_artifact
          RECAP_HERMES_AUTH_ARTIFACT="none"
          printf '%s %s\n' \
            "$(gum style --foreground 10 'Hermes auth:')" \
            "$(gum style --foreground 14 "Login skipped or failed")"
        fi
      else
        clear_local_hermes_auth_artifact
        RECAP_HERMES_AUTH_ARTIFACT="none"
        printf '%s %s\n' \
          "$(gum style --foreground 10 'Hermes auth:')" \
          "$(gum style --foreground 14 "Skipped for now")"
      fi
    else
      clear_local_hermes_auth_artifact
      RECAP_HERMES_AUTH_ARTIFACT="none"
      printf '%s %s\n' \
        "$(gum style --foreground 10 'Hermes auth:')" \
        "$(gum style --foreground 14 "${HERMES_PROVIDER} uses non-.env auth; run hermes auth/model/setup separately")"
    fi
  fi
fi

clear_screen
render_step_box 4

EXISTING_TELEGRAM_BOT_TOKEN="$(get_env_value TELEGRAM_BOT_TOKEN)"
NEEDS_TELEGRAM_BOT_TOKEN="yes"
if has_usable_secret_value "${EXISTING_TELEGRAM_BOT_TOKEN}"; then
  set +e
  gum confirm --default=false "Existing TELEGRAM_BOT_TOKEN found in .env. Set a new token?"
  telegram_token_confirm_rc=$?
  set -e
  if [[ "${telegram_token_confirm_rc}" -ne 0 ]]; then
    NEEDS_TELEGRAM_BOT_TOKEN="no"
  fi
fi

if [[ "${NEEDS_TELEGRAM_BOT_TOKEN}" == "yes" ]]; then
  print_telegram_token_setup
  TELEGRAM_BOT_TOKEN_VALUE="$(gum input --password --placeholder 'Paste TELEGRAM_BOT_TOKEN')"
  if [[ -z "${TELEGRAM_BOT_TOKEN_VALUE}" ]]; then
    echo "ERROR: TELEGRAM_BOT_TOKEN cannot be empty." >&2
    exit 1
  fi
  set_env_value "TELEGRAM_BOT_TOKEN" "${TELEGRAM_BOT_TOKEN_VALUE}"
fi
printf '%s %s\n' \
  "$(gum style --foreground 10 'Telegram bot token:')" \
  "$(gum style --foreground 14 'configured')"

print_telegram_user_id_setup
EXISTING_TELEGRAM_ALLOWLIST_IDS="$(get_env_value TELEGRAM_ALLOWLIST_IDS)"
TELEGRAM_ALLOWLIST_IDS_INPUT="$(gum input --header 'Paste Telegram user ID (or comma-separated IDs)' --header.foreground 99 --placeholder "${EXISTING_TELEGRAM_ALLOWLIST_IDS:-example: 12345,-100987654321}")"
if [[ -n "${TELEGRAM_ALLOWLIST_IDS_INPUT}" ]]; then
  TELEGRAM_ALLOWLIST_IDS_VALUE="${TELEGRAM_ALLOWLIST_IDS_INPUT}"
else
  TELEGRAM_ALLOWLIST_IDS_VALUE="${EXISTING_TELEGRAM_ALLOWLIST_IDS}"
fi
if [[ -z "${TELEGRAM_ALLOWLIST_IDS_VALUE}" ]]; then
  echo "ERROR: TELEGRAM_ALLOWLIST_IDS cannot be empty." >&2
  exit 1
fi
if ! [[ "${TELEGRAM_ALLOWLIST_IDS_VALUE}" =~ ^-?[0-9]+(,-?[0-9]+)*$ ]]; then
  echo "ERROR: TELEGRAM_ALLOWLIST_IDS must be comma-separated integers (example: 12345,-100987654321)." >&2
  exit 1
fi
set_env_value "TELEGRAM_ALLOWLIST_IDS" "${TELEGRAM_ALLOWLIST_IDS_VALUE}"
printf '%s %s\n' \
  "$(gum style --foreground 10 'Telegram allowlist IDs:')" \
  "$(gum style --foreground 14 "${TELEGRAM_ALLOWLIST_IDS_VALUE}")"

RECAP_SSH_ALIAS="skipped"
set +e
gum confirm --default=true "Add SSH alias 'hermes-vps' via ~/.ssh/config Include?"
ssh_alias_confirm_rc=$?
set -e
if [[ "${ssh_alias_confirm_rc}" -eq 0 ]]; then
  SSH_ALIAS_PORT="${BOOTSTRAP_SSH_PORT:-22}"
  if ensure_repo_ssh_alias "${SELECTED_ADMIN_USERNAME}" "${SELECTED_SSH_KEY_PATH}" "${SSH_ALIAS_PORT}" "${SELECTED_HOSTNAME}"; then
    RECAP_SSH_ALIAS="added"
    printf '%s %s\n' \
      "$(gum style --foreground 10 'SSH alias:')" \
      "$(gum style --foreground 14 "added (ssh hermes-vps)")"
  else
    RECAP_SSH_ALIAS="already present"
    printf '%s %s\n' \
      "$(gum style --foreground 10 'SSH alias:')" \
      "$(gum style --foreground 14 "already present")"
  fi
fi

chmod 600 "${ENV_FILE}" || true

exit_alt_screen
render_done_box

printf '%s %s\n' \
  "$(gum style --foreground 10 'Cloud:')" \
  "$(gum style --foreground 14 "${PROVIDER}")"
printf '%s %s\n' \
  "$(gum style --foreground 10 'Server image:')" \
  "$(gum style --foreground 14 "${SERVER_IMAGE}")"
printf '%s %s\n' \
  "$(gum style --foreground 10 'Region:')" \
  "$(gum style --foreground 14 "${SELECTED_REGION_LABEL}")"
printf '%s %s\n' \
  "$(gum style --foreground 10 'Server type:')" \
  "$(gum style --foreground 14 "${SELECTED_TYPE_LABEL}")"
printf '%s %s\n' \
  "$(gum style --foreground 10 'Hostname:')" \
  "$(gum style --foreground 14 "${SELECTED_HOSTNAME}")"
printf '%s %s\n' \
  "$(gum style --foreground 10 'Admin username:')" \
  "$(gum style --foreground 14 "${SELECTED_ADMIN_USERNAME}")"
printf '%s %s\n' \
  "$(gum style --foreground 10 'SSH group:')" \
  "$(gum style --foreground 14 "${SELECTED_ADMIN_GROUP}")"
printf '%s %s\n' \
  "$(gum style --foreground 10 'SSH key:')" \
  "$(gum style --foreground 14 "${SELECTED_SSH_KEY_PATH}")"
printf '%s %s\n' \
  "$(gum style --foreground 10 'Hermes Agent version:')" \
  "$(gum style --foreground 14 "${HERMES_AGENT_VERSION}")"
printf '%s %s\n' \
  "$(gum style --foreground 10 'Provider:')" \
  "$(gum style --foreground 14 "${HERMES_PROVIDER}")"
printf '%s %s\n' \
  "$(gum style --foreground 10 'Model:')" \
  "$(gum style --foreground 14 "${HERMES_MODEL}")"
printf '%s %s\n' \
  "$(gum style --foreground 10 'Auth type:')" \
  "$(gum style --foreground 14 "${RECAP_HERMES_AUTH_TYPE}")"
printf '%s %s\n' \
  "$(gum style --foreground 10 'Auth artifact:')" \
  "$(gum style --foreground 14 "${RECAP_HERMES_AUTH_ARTIFACT}")"
printf '%s %s\n' \
  "$(gum style --foreground 10 'Telegram bot token:')" \
  "$(gum style --foreground 14 'configured')"
printf '%s %s\n' \
  "$(gum style --foreground 10 'Telegram allowlist IDs:')" \
  "$(gum style --foreground 14 "${TELEGRAM_ALLOWLIST_IDS_VALUE}")"
printf '%s %s\n' \
  "$(gum style --foreground 10 'SSH alias:')" \
  "$(gum style --foreground 14 "${RECAP_SSH_ALIAS}")"

gum style --foreground 99 "Configuration complete."
gum style --foreground 99 "Next: run 'just bootstrap'."
