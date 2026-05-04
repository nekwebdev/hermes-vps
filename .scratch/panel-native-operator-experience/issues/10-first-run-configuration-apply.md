# First-run configuration Apply with Host & SSH and OAuth persistence

Status: needs-triage

## Parent

.scratch/panel-native-operator-experience/PRD.md

## What to build

Replace the first-run Review placeholder with a real `Apply configuration` action. This is the global configuration Apply boundary for the first-run wizard: it writes `.env`, performs promised Host & SSH apply-time effects, and persists the captured Hermes OAuth artifact when OAuth mode is selected. It must not auto-run Deployment.

## In scope

- First-run Review screen only:
  - Add `Apply configuration` button.
  - Run Apply in a Textual worker.
  - Disable the button while applying.
  - Show visible progress/final status.
  - On success, show `Configuration applied.`, `.env written.`, Host & SSH success lines, optional `Hermes OAuth artifact written.`, and a separate `Next: Deploy` action/guidance.
- Reusable config-flow Apply behavior:
  - Validate the Review is still applyable.
  - Ensure SSH key material at the selected path, creating an ed25519 key pair if missing.
  - chmod private key `0600` and public key `0644`.
  - Use the public key to write/update `TF_VAR_admin_ssh_public_key` in `.env`.
  - Preserve/update `BOOTSTRAP_SSH_PRIVATE_KEY_PATH` using the final key path.
  - Write `.env` via existing `EnvStore.ensure() -> set(...) -> flush()` behavior so missing `.env` is created from `.env.example`, template comments/structure are retained, and mode is `0600`.
  - Reconcile the local SSH alias `hermes-vps` at Apply when selected.
  - Remove only repo-owned SSH alias/include artifacts when unselected.
  - For OAuth mode with a fresh captured artifact, write `.hermes-home/.auth.json.tmp` mode `0600`, then finalize to `.hermes-home/auth.json` only after `.env` and SSH side effects succeed.
  - Clear raw in-memory OAuth artifact bytes after successful durable write.
- Review action lines outside the `.env` diff:
  - `SSH key: will ensure <operator-entered-path>`
  - `SSH public key: will update TF_VAR_admin_ssh_public_key`
  - `SSH alias: active` or `SSH alias: inactive`
  - OAuth mode only: `Hermes OAuth artifact: captured for <provider> <version> (<fingerprint-prefix>), will write .hermes-home/auth.json at Apply.`
- Secret safety:
  - Do not render private key material, public key body, raw `auth.json`, token payloads, full SHA-256, or `.cache` OAuth draft paths.

## Out of scope

- Reconfigure Review/Apply UI replacement.
- Reconfigure keep-existing OAuth artifact UI.
- Deployment/OpenTofu `apply`, `deploy`, `bootstrap`, or `verify` execution.
- Bootstrap staging from `.hermes-home/auth.json` to `bootstrap/runtime/hermes-auth.json`.
- Typed/destructive confirmation. First-run configuration Apply is a single explicit click.

## Apply ordering

1. Validate Review is applyable.
2. Ensure SSH key material and update env patch inputs.
3. Prepare OAuth temp artifact if OAuth mode has a fresh captured artifact.
4. Write `.env` through the existing template-preserving EnvStore path.
5. Reconcile/remove the SSH alias.
6. Rename `.hermes-home/.auth.json.tmp` to `.hermes-home/auth.json` if OAuth mode applies.
7. Clear in-memory OAuth artifact bytes.
8. Render success without auto-running Deployment.

## Failure semantics

- If Review is not applyable, block Apply with the review blocking issue text.
- If `.env` writing fails, delete `.hermes-home/.auth.json.tmp` if present, report `Configuration apply failed. No OAuth artifact was written.`, and do not mark configuration complete.
- If SSH alias reconciliation fails after `.env` succeeds, report `Configuration apply incomplete: .env was written but SSH alias was not reconciled. Retry Apply.`, leave `.env` as written, keep any not-yet-finalized in-memory OAuth artifact, and do not mark configuration complete.
- If OAuth final rename fails after `.env` and SSH side effects succeed, report `Configuration apply incomplete: .env was written but Hermes OAuth artifact was not finalized. Retry Apply.`, keep the in-memory OAuth artifact for retry, and do not mark configuration complete.
- Do not rollback `.env` after partial failure; retry is idempotent.

## Acceptance criteria

- [ ] First-run Review renders `Apply configuration` and no longer stops at a static diff/helper-only placeholder.
- [ ] Applying runs in a Textual worker and disables the Apply button while running.
- [ ] Successful API-key-mode Apply writes `.env`, preserves `.env.example` comments when seeding missing `.env`, enforces `.env` mode `0600`, ensures SSH key material, writes `TF_VAR_admin_ssh_public_key`, reconciles/removes SSH alias as selected, and does not create `.hermes-home/auth.json`.
- [ ] Successful OAuth-mode Apply writes `.env`, ensures Host & SSH side effects, writes `.hermes-home/auth.json` with owner-only permissions, clears raw in-memory OAuth bytes after success, and shows `Hermes OAuth artifact written.`
- [ ] Review shows Host & SSH and OAuth action lines outside the `.env` diff and does not render private key material, public key body, raw auth JSON, full SHA-256, token payloads, or OAuth draft cache paths.
- [ ] Missing `.env` path creates `.env` from `.env.example`, retains comments/structure, upserts changed keys, and chmods `0600`.
- [ ] SSH alias reconciliation is idempotent: ensure updates one repo-owned `Host hermes-vps` block and one home `Include` line; remove deletes only repo-owned alias/include artifacts and preserves unrelated SSH config.
- [ ] `.env` write failure deletes any OAuth temp artifact and reports failure without success/Next Deploy state.
- [ ] SSH alias failure after `.env` write reports the incomplete retryable message, keeps OAuth artifact in memory if needed, and does not mark configuration complete.
- [ ] OAuth rename failure after `.env` and SSH success reports the incomplete retryable message, keeps OAuth artifact in memory for retry, and does not mark configuration complete.
- [ ] Successful Apply shows success in-place and offers `Next: Deploy` or equivalent guidance, but does not auto-run Deployment.
- [ ] Focused tests pass for config-flow service behavior and Textual first-run Review wiring.

## References

- `CONTEXT.md` glossary entries: configuration Apply seed policy, env writer policy, first-run configuration Apply completion, Host & SSH effects, Apply ordering, OAuth failure semantics, Review action displays, Apply confirmation/worker policy.
- `docs/adr/0005-hermes-oauth-artifact-lifecycle.md` Apply transaction section.
- `scripts/configure_services.py` legacy `ConfigureOrchestrator.apply()` for SSH key and alias behavior.
