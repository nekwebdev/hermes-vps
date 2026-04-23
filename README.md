# OpenTofu + cloud-init + idempotent bootstrap VPS baseline (Debian 12)

Single-person production VPS baseline that supports both Hetzner and Linode from one repository, with local OpenTofu state, CIS L1-inspired hardening, Hermes Agent, and Telegram gateway.

## Why nftables (instead of ufw)
Debian 12 uses nftables natively. Choosing nftables removes an extra abstraction layer, keeps rules deterministic in `/etc/nftables.conf`, and aligns directly with fail2ban `nftables-*` actions.

## Threat model assumptions
- Internet-exposed single VPS with SSH as primary admin entry point.
- Admin machine is trusted and holds private SSH key.
- Provider account/API token compromise is out of scope for host hardening; protect provider accounts separately with MFA.
- Telegram bot token secrecy and allowlist integrity are required to prevent unauthorized command execution.

## Repository layout
- `opentofu/modules/common-vps/`: shared cloud-init rendering and normalized tags.
- `opentofu/providers/hetzner/`: Hetzner-specific resources.
- `opentofu/providers/linode/`: Linode-specific resources.
- `opentofu/cloud-init/`: cloud-init templates.
- `bootstrap/`: idempotent host-configuration scripts.
- `templates/`: deterministic config templates copied to system paths.
- `flake.nix`: Nix dev environment containing OpenTofu, Just, SSH tooling.
- `scripts/toolchain.sh`: runs commands through `nix develop`; falls back to Docker+Nix when host nix is unavailable.

## Prerequisites
On your local workstation:
- `git`
- `bash`
- Either:
  - Nix with flakes enabled, or
  - Docker (fallback path used by `scripts/toolchain.sh`)

Note: you do not need local OpenTofu/Just preinstalled because the flake supplies them.

## Fresh clone quickstart
1. Clone and enter repo.
2. Copy env template and fill values.
   - Set `HERMES_AGENT_VERSION` to a pinned release version (required by bootstrap).
   - Keep `.env` permissions strict (`chmod 600 .env`), because Justfile preflight enforces this.
3. Run deploy flow with Just targets.

```bash
git clone <your-repo-url> hermes-vps
cd hermes-vps
cp .env.example .env
chmod 600 .env
# edit .env with real values

just init
# optional explicit provider/plugin refresh
just init-upgrade
just plan
just apply
just bootstrap
just verify
```

## Provider selection flow
The Just interface uses one provider selector variable:
- `PROVIDER` (default: `hetzner`)
- Override per command, for example: `just plan PROVIDER=linode`

Provider API token values still come from `.env`:
- Hetzner: `HCLOUD_TOKEN`
- Linode: `LINODE_TOKEN`

OpenTofu working directory is derived from `PROVIDER`:
- `opentofu/providers/hetzner`
- `opentofu/providers/linode`

## End-to-end commands
```bash
# default provider (hetzner)
just init
just init-upgrade
just plan
just apply
just bootstrap
just verify
just logs
just hardening-audit

# provider override example
just plan PROVIDER=linode
just apply PROVIDER=linode

# logs examples
just logs
just logs SERVICE=hermes
```

Destroy requires explicit confirmation:
```bash
just destroy CONFIRM=YES
# or alias
just down CONFIRM=YES
```

Before destroy runs, the Justfile now creates a timestamped local state backup archive when state files exist:
- path: `.state-backups/<provider>/tfstate-<UTC_TIMESTAMP>.tar.gz`
- mode: `0600`
- note: archive is local and unencrypted by default; encrypt before off-host storage.

## Idempotence and re-run guidance
- Re-run safe operations anytime:
  - `just plan`
  - `just bootstrap`
  - `just verify`
  - `just hardening-audit`
- Scripts avoid duplicate users/groups/services and use deterministic file replacement.
- `sshd` config is validated (`sshd -t`) before restart.
- Service restart occurs only when unit/script/env content changed, package version changed, or service is not active.

## Verification checklist
After `just bootstrap` + `just verify`:
- `sshd -T` reports:
  - `permitrootlogin no`
  - `passwordauthentication no`
  - `pubkeyauthentication yes`
  - `allowgroups sshadmins`
- `nftables`, `fail2ban`, `systemd-timesyncd`, `unattended-upgrades`, `hermes`, `telegram-gateway` are active.
- `/etc/hermes/hermes.env` and `/etc/telegram-gateway/gateway.env` are `0600 root:root`.
- New SSH session login as admin user works before closing original session.

## Local OpenTofu state protection
This repository intentionally uses local state only.

Recommendations:
- Keep repository on encrypted disk.
- Restrict permissions on local `.tfstate` files.
- Exclude all state files from Git (`.gitignore` already does this).
- Back up state with encryption (for example, age or gpg encrypted archive) to offline or private storage.
- Before destructive operations, make a timestamped encrypted backup of the provider directory state files.

## Break-glass recovery runbook
### Scenario A: SSH lockout after hardening
1. Keep existing SSH session open.
2. Validate config:
   ```bash
   sudo sshd -t
   sudo systemctl status ssh
   ```
3. If broken, restore prior config in active session:
   ```bash
   sudo cp /etc/ssh/sshd_config /etc/ssh/sshd_config.broken.$(date +%s)
   sudoedit /etc/ssh/sshd_config
   sudo sshd -t && sudo systemctl restart ssh
   ```
4. Confirm a second SSH login succeeds before ending original session.

### Scenario B: Full lockout / no SSH access
1. Use provider rescue/console mode (Hetzner Rescue or Linode LISH).
2. Mount root filesystem and revert `/etc/ssh/sshd_config` to permit key login for admin group.
3. Disable nftables temporarily if rule error blocked SSH:
   ```bash
   systemctl stop nftables
   nft flush ruleset
   ```
4. Reboot normally and rerun `bootstrap/20-hardening.sh` after fixing template values.

### Scenario C: Telegram gateway not responding
1. Check service logs:
   ```bash
   sudo journalctl -u telegram-gateway --no-pager -n 200
   ```
2. Verify token and allowlist env file values and permissions.
3. Restart service:
   ```bash
   sudo systemctl restart telegram-gateway
   ```

## Health checks and log inspection
```bash
sudo systemctl status hermes telegram-gateway fail2ban nftables ssh
sudo journalctl -u hermes -u telegram-gateway --no-pager -n 200
sudo fail2ban-client status
sudo nft list ruleset
```

## Safety note
Always keep your active SSH session open while applying hardening changes, and only close it after a second independent SSH login test passes.
