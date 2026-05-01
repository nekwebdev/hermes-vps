# Destructive destroy UX and audit hardening v2

Status: completed

## Parent

.scratch/control-panel-v2-hardening-docs-cutover/PRD.md

## What to build

Route destroy preview, approval, denial, execution status, and audit metadata through the v2 presentation/result contracts while preserving the destructive-action gate and local state backup behavior.

## Acceptance criteria

- [ ] Destroy preview remains exact and non-secret: provider, OpenTofu provider directory, backup behavior, state file summary, and safe outputs when available.
- [ ] Interactive and headless destructive approval still require the existing destroy token contract.
- [ ] Denied destroy attempts render through shared taxonomy and do not echo raw bad tokens.
- [ ] Approved destroy output includes graph/action status, backup status/path where applicable, runner mode, and repair scope on failure.
- [ ] Audit/session output records approved and denied destructive paths with canonical token usage only when approved and no raw bad-token leakage.
- [ ] Fake-runner tests cover preview-only, denied, approved, backup metadata, JSON output, and human output paths.

## Blocked by

- .scratch/control-panel-v2-hardening-docs-cutover/issues/02-deterministic-exit-codes-and-error-taxonomy-for-headless-commands.md
- .scratch/control-panel-v2-hardening-docs-cutover/issues/03-graph-preview-and-repair-scope-rendering-for-state-changing-workflows.md
- .scratch/control-panel-v2-hardening-docs-cutover/issues/04-action-result-and-event-stream-schema-hardening-with-bounded-output-tails.md
