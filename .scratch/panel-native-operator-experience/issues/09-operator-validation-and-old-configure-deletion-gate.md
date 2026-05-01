# Add operator validation gate before deleting old configure code

Status: completed

## Parent

.scratch/panel-native-operator-experience/PRD.md

## What to build

Create the explicit validation checklist and tracking gate for deleting old configure code. Do not delete old configure implementation in this slice unless the checklist has been completed and HITL approval is recorded.

## Acceptance criteria

- [x] Validation checklist covers regression parity tests for missing `.env`, existing `.env`, keep-existing secrets, provider switch dependency review, live lookup remediation, stale async validation, atomic write, and secret-safe previews.
- [x] Manual/operator checklist covers fresh repo, existing Hetzner config, existing Linode config if feasible, bad permissions remediation, and token keep/replace paths.
- [x] Checklist verifies `just configure` and `just panel` route into the same app.
- [x] Documentation names the old configure code as temporary source material only.
- [x] Old configure deletion requires explicit HITL approval after checklist completion.
- [x] If approval is not present, the issue documents what remains and leaves old code intact.

## Blocked by

- 05-configuration-first-run-and-reconfigure-panel.md
- 06-deployment-panel-aggregate-and-advanced-progress.md
- 07-maintenance-and-monitoring-panel-wiring.md
- 08-panel-host-override-and-remediation-ux.md

## Validation gate created

The operator gate is documented in `docs/operator-validation-configure-deletion.md`. It is a tracking checklist and evidence record only; it is not deletion approval.

### Automated regression parity checklist

- [ ] Missing `.env`: fresh repository startup routes to the configuration-required path; configure can create `.env` from `.env.example`; generated file is mode `0600` and no secrets are printed.
- [ ] Existing `.env`: startup reads existing provider and non-secret settings without overwriting values during preview.
- [ ] Keep-existing secrets: blank/keep paths preserve existing `HCLOUD_TOKEN`, `LINODE_TOKEN`, `HERMES_API_KEY`, Telegram token fields, and SSH key paths unless replacement is explicitly requested.
- [ ] Provider switch dependency review: switching `TF_VAR_cloud_provider` shows provider-specific dependencies, warns about token requirements, and does not silently carry provider-incompatible values.
- [ ] Live lookup remediation: failed live provider lookup surfaces actionable remediation without leaking tokens and does not write partial invalid configuration.
- [ ] Stale async validation: async validation results are scoped to the current input/provider snapshot; stale results cannot overwrite newer validation state.
- [ ] Atomic write: saving configuration writes through a temporary file plus atomic replace, preserves or remediates mode `0600`, and does not leave truncated `.env` on failure.
- [ ] Secret-safe previews: preview/diff output redacts secrets and never displays raw API tokens, bot tokens, private keys, OAuth artifacts, or full `.env` contents.

### Manual/operator validation checklist

- [ ] Fresh repo: clone or clean checkout with no `.env`, run `just configure`, complete minimum required values, then run `just panel` and verify the dashboard reads the same saved configuration.
- [ ] Existing Hetzner config: with a known-good Hetzner `.env`, run `just panel`, enter configuration, keep existing secrets, save, and verify Hetzner plan/preflight still targets Hetzner.
- [ ] Existing Linode config if feasible: with a known-good Linode `.env`, run `just panel`, enter configuration, keep existing secrets, save, and verify Linode plan/preflight still targets Linode. If no Linode credentials are available, record why this item is infeasible and keep deletion blocked.
- [ ] Bad permissions remediation: set `.env` to an unsafe mode such as `0644`, launch configuration, verify the UI reports/remediates permissions to `0600`, and verify no secret values appear in output.
- [ ] Token keep path: retain existing provider/API/Telegram tokens through a save and verify the file still contains the original values while previews remain redacted.
- [ ] Token replace path: replace provider/API/Telegram tokens intentionally, save, verify only the selected tokens changed, and verify previews remain redacted.
- [ ] Route parity: verify `just configure` and `just panel` both route into `hermes_vps_app.panel_entrypoint` with the same repo root; `just configure` only adds `--initial-panel configuration`.

### Temporary source material and HITL block

The old configure code, including `scripts/configure_tui.py`, is temporary source material only. It remains available for comparison during validation, but operators should use the native panel route as the canonical app path.

Old configure deletion requires all checklist items to be completed, evidence to be recorded, and explicit HITL approval after checklist completion. No explicit HITL approval is recorded in this issue. Approval status: not approved.

What remains because approval is absent:

- Old configure implementation remains intact.
- Deletion remains blocked pending completed checklist evidence and explicit HITL approval.
- A future deletion slice must update `docs/operator-validation-configure-deletion.md`, record HITL approval, and only then remove old configure code in a separate reviewed change.

## Checks

- `./scripts/toolchain.sh "python3 -m pytest tests/test_operator_validation_configure_deletion_gate_issue09.py -q"`
