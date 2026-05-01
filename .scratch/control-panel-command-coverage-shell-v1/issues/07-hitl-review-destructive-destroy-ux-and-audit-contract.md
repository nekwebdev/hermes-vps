# HITL review: destructive destroy UX and audit contract

Status: completed

## Parent

.scratch/control-panel-command-coverage-shell-v1/PRD.md

## What to build

Run the required human-in-the-loop review for the destructive `destroy` workflow before implementation. Decide the exact preview scope, confirmation wording/token or equivalent UX action, non-interactive approval flag, and audit fields needed for the Python control panel migration.

## Acceptance criteria

- [ ] Destroy preview scope is explicitly approved and includes only non-secret data: provider, OpenTofu provider directory, state backup root/path behavior, and known target/resource identifiers available from safe calls.
- [ ] Interactive destructive confirmation UX is approved, including exact wording and required token/action.
- [ ] Non-interactive destructive approval flag name and behavior are approved.
- [ ] Audit fields for approved and denied destructive attempts are approved.
- [ ] Interaction between host override escalation and destructive confirmation is explicitly documented: separate gates, both required when both policies apply.
- [ ] Decision notes are appended to this issue or referenced from this issue before the destroy implementation issue starts.

## Decision notes

Approved HITL contract:

- Destroy preview scope includes only non-secret data: provider, OpenTofu provider directory, backup root/path behavior, local state files count/list, and known safe OpenTofu outputs (`public_ipv4`, `admin_username`, optional server/resource IDs if already exposed by outputs).
- Interactive confirmation requires exact token `DESTROY <provider>` after preview.
- Headless/non-interactive approval flag is `--approve-destructive DESTROY:<provider>`; absent or mismatched approval denies before backup or OpenTofu destroy.
- Audit fields: action_id, provider, tf_dir, backup_path/status, approved bool, confirmation_mode (`interactive|headless`), approved_by (`operator|cli_flag`), timestamp, target_summary, host_override_required/approved, and canonical token usage only. Raw bad tokens must not be stored or echoed.
- Host override remains a separate gate. When HostRunner and destroy are both used, both `I-ACK-HOST-OVERRIDE` and destructive approval are required.

## Blocked by

- .scratch/control-panel-command-coverage-shell-v1/issues/01-init-command-tracer-bullet-through-headless-app-runner-graph-and-just-shim.md
