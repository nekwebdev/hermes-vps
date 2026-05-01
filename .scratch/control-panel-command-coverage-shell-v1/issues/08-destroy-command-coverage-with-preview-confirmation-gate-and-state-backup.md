# Destroy command coverage with preview, confirmation gate, and state backup

Status: completed

## Parent

.scratch/control-panel-command-coverage-shell-v1/PRD.md

## What to build

Migrate `destroy` into the Python control panel command coverage path using the approved destructive UX and audit contract. The graph should show a non-secret destructive preview, require confirmation, back up local state when present, and then run OpenTofu destroy through the locked runner.

## Acceptance criteria

- [ ] A public headless Python entrypoint can run the `destroy` action graph for the selected provider only when destructive approval requirements are satisfied.
- [ ] Destroy preview shows the approved exact non-secret scope before teardown.
- [ ] Interactive destroy without confirmation is denied before side effects.
- [ ] Non-interactive destroy without explicit approval flag is denied before side effects.
- [ ] Approved destroy records audit metadata for the destructive approval.
- [ ] State backup behavior is preserved: local state files are archived under the provider backup path with restrictive mode before destroy runs.
- [ ] OpenTofu destroy command construction uses argv and validated provider paths.
- [ ] Host runner override remains independently enforced and denied attempts do not echo provided token values.
- [ ] Action events, graph results, audit records, and errors do not contain raw secrets.
- [ ] Migrated `just destroy` and `just down` delegate to the Python entrypoint where feasible while preserving compatible confirmation and exit behavior.
- [ ] Behavioral tests cover preview, denied confirmation, non-interactive approval, state backup, audit metadata, host override gate, no-token-leak denial, command construction, fail-fast behavior, and Just shim parity.
- [ ] Changed Python passes through `./scripts/toolchain.sh`: `python3 -m pytest ...`, `python3 -m ruff check ...`, and `basedpyright ...`.

## Blocked by

- .scratch/control-panel-command-coverage-shell-v1/issues/07-hitl-review-destructive-destroy-ux-and-audit-contract.md
