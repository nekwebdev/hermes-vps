# Operator validation gate for old configure deletion

This document is the gate for any future deletion of the old configure implementation. It is intentionally a checklist and evidence record, not approval to delete code.

Current decision: deletion blocked. No explicit HITL approval is recorded after checklist completion.

Temporary source material only:
- `scripts/configure_tui.py` and any old configure helper modules are retained only as temporary source material while the native panel configure flow is validated.
- Do not route operators to `scripts.configure_tui` as the canonical configure experience.
- Do not delete these files until this checklist is completed, evidence is attached, and HITL approval is explicitly recorded below.

Canonical route requirement:
- `just panel` must launch `python3 -m hermes_vps_app.panel_entrypoint --repo-root .`.
- `just configure` must launch the same app, `python3 -m hermes_vps_app.panel_entrypoint --repo-root . --initial-panel configuration`.
- The only expected difference is the initial panel selection; both commands must route into the same Textual control panel application.

Automated regression parity checklist:
- [ ] Missing `.env`: fresh repository startup routes to the configuration-required path; configure can create `.env` from `.env.example`; generated file is mode `0600` and no secrets are printed.
- [ ] Existing `.env`: startup reads existing provider and non-secret settings without overwriting values during preview.
- [ ] Keep-existing secrets: blank/keep paths preserve existing `HCLOUD_TOKEN`, `LINODE_TOKEN`, `HERMES_API_KEY`, Telegram token fields, and SSH key paths unless replacement is explicitly requested.
- [ ] Provider switch dependency review: switching `TF_VAR_cloud_provider` shows provider-specific dependencies, warns about token requirements, and does not silently carry provider-incompatible values.
- [ ] Live lookup remediation: failed live provider lookup surfaces actionable remediation without leaking tokens and does not write partial invalid configuration.
- [ ] Stale async validation: async validation results are scoped to the current input/provider snapshot; stale results cannot overwrite newer validation state.
- [ ] Atomic write: saving configuration writes through a temporary file plus atomic replace, preserves or remediates mode `0600`, and does not leave truncated `.env` on failure.
- [ ] Secret-safe previews: preview/diff output redacts secrets and never displays raw API tokens, bot tokens, private keys, OAuth artifacts, or full `.env` contents.

Manual/operator validation checklist:
- [ ] Fresh repo: clone or clean checkout with no `.env`, run `just configure`, complete minimum required values, then run `just panel` and verify the dashboard reads the same saved configuration.
- [ ] Existing Hetzner config: with a known-good Hetzner `.env`, run `just panel`, enter configuration, keep existing secrets, save, and verify Hetzner plan/preflight still targets Hetzner.
- [ ] Existing Linode config if feasible: with a known-good Linode `.env`, run `just panel`, enter configuration, keep existing secrets, save, and verify Linode plan/preflight still targets Linode. If no Linode credentials are available, record why this item is infeasible and keep deletion blocked.
- [ ] Bad permissions remediation: set `.env` to an unsafe mode such as `0644`, launch configuration, verify the UI reports/remediates permissions to `0600`, and verify no secret values appear in output.
- [ ] Token keep path: retain existing provider/API/Telegram tokens through a save and verify the file still contains the original values while previews remain redacted.
- [ ] Token replace path: replace provider/API/Telegram tokens intentionally, save, verify only the selected tokens changed, and verify previews remain redacted.
- [ ] Route parity: run or inspect both Just recipes and record that `just configure` and `just panel` route into `hermes_vps_app.panel_entrypoint` with the same repo root and only differ by `--initial-panel configuration`.

Evidence required before HITL approval:
- Automated test command(s): not recorded.
- Manual validation operator/date: not recorded.
- Fresh repo evidence: not recorded.
- Existing Hetzner evidence: not recorded.
- Existing Linode evidence or infeasibility note: not recorded.
- Bad permissions evidence: not recorded.
- Token keep/replace evidence: not recorded.
- Route parity evidence: not recorded.

HITL approval record:
- Approval status: not approved.
- Approver: not recorded.
- Approval date: not recorded.
- Approval statement: not recorded.

What remains because approval is absent:
- Old configure implementation remains intact.
- Deletion remains blocked pending completed checklist evidence and explicit HITL approval.
- A future deletion slice must update this record with evidence, record HITL approval, and then remove old configure code in a separate reviewed change.
