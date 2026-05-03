# ADR-0004: Selected-Version Hermes Toolchain Cache

Status: Accepted
Date: 2026-05-02

## Context

The panel Hermes configuration step must replace placeholder provider/model/auth options with live Hermes Agent metadata. That metadata must match the Hermes version the operator selects and the version Review/Apply will persist as `HERMES_AGENT_VERSION` plus `HERMES_AGENT_RELEASE_TAG`.

Using whichever `hermes` happens to be installed globally would introduce drift: the panel could show provider/model/auth options for a different Hermes version than the one the VPS will install. PyPI is not currently a viable source for Nous Hermes Agent (`hermes-agent` is not published there), and the similarly named `hermes-cli` package is unrelated.

The canonical upstream installer at `scripts/install.sh` clones the `NousResearch/hermes-agent` repository, checks out a branch/tag, creates a Python 3.11 virtual environment with `uv`, and installs the checkout editable with `uv pip install -e '.[all]'`. The installer also performs user-facing side effects such as writing config templates and creating command symlinks, which are not appropriate for passive panel metadata loading.

## Decision

Implement service-first inside `hermes_vps_app`, with shell/subprocess work encapsulated by typed services. Thin scripts may be added later only for debugging; the panel should call services directly.

Use a repo-owned, selected-version Hermes toolchain cache for panel metadata and later explicit auth commands.

1. Release discovery
- Fetch the latest five Hermes Agent releases from GitHub REST: `https://api.github.com/repos/NousResearch/hermes-agent/releases?per_page=5`.
- Parse semantic package versions from release `name`/`body` and use `tag_name` as the linked release tag.
- The release list may use a short in-process TTL cache, initially 5 minutes.
- Manual Retry or explicit refresh bypasses the TTL.
- Release fetch is unauthenticated in this slice; do not add a `GITHUB_TOKEN` path unless rate limits become a demonstrated problem.

2. Cache layout
- Cache selected Hermes installs under `.cache/hermes-toolchain/<semver>-<release-tag>/`.
- Each cache entry contains `src`, `venv`, a cache-local `home`, and `.ready.json`.
- Build into `.cache/hermes-toolchain/.building/<semver>-<release-tag>-<request_id>/` first, guarded by `.cache/hermes-toolchain/.locks/<semver>-<release-tag>.lock`, then atomically move the successful build into the final cache path.
- The directory key is only `<semver>-<release-tag>`; the resolved git commit is stored in `.ready.json` and used for validation/invalidation.

3. Install method
- Add `uv` to `flake.nix` as an in-scope prerequisite for the live metadata slice.
- Clone/fetch the selected GitHub release tag into `src`.
- Create `venv` with `uv venv --python 3.11`.
- Install the checkout with `uv pip install -e '.[all]'`.
- Fail closed if the full extras install fails. Do not silently fall back to base install.

4. Readiness and smoke tests
- Treat `.ready.json` as the cache readiness contract, not the mere existence of `venv/bin/hermes`.
- Smoke-test `venv/bin/hermes --version` and provider/model metadata imports before marking ready.
- `.ready.json` records semantic version, release tag, git commit, install mode `editable-all`, Python version, Hermes CLI path, creation timestamp, and smoke-test result.
- If a release tag later resolves to a different commit than the sentinel records, treat the cache as stale/corrupt and rebuild.

5. Execution
- Execute Hermes through explicit selected-version paths such as `.cache/hermes-toolchain/0.12.0-v2026.4.30/venv/bin/hermes`.
- Do not use a global `hermes` command or an `active` symlink for panel execution.
- Version switching means changing the draft-selected version and resolving that version's explicit cache path.
- An optional `current` symlink may exist only for developer debugging and must not be used by panel execution.

6. Async/stale behavior
- Correlate cache preparation by `(semantic_version, release_tag, request_id)`.
- If the operator changes version while an install is running, do not kill the old install by default; let it finish and warm its cache.
- Accept a cache/install result only if it still matches the current selected version and latest request id.
- Stale install success is retained silently as cache warmth.
- Stale install failure is logged/debug-only and must not surface as the current UI error.
- Current selected-version install failure blocks Hermes with Retry.

7. HERMES_HOME separation
- Passive metadata commands run with an isolated cache-local `HERMES_HOME`, for example `.cache/hermes-toolchain/<semver>-<release-tag>/home`.
- Passive metadata sync must not read or write the developer's real `~/.hermes` or any future project auth home.
- Future explicit OAuth/auth actions will need a repo-owned target Hermes home/path. The likely target is root-level `.hermes-home/`, gitignored and treated as durable local operator state, but that remains a future auth-slice decision.
- Do not create `.hermes-home/` or wire it into the live metadata slice.

8. Side effects avoided
- Do not run the full upstream install script from the panel cache builder.
- Do not create global/user `hermes` symlinks.
- Do not copy user config templates, start setup, start gateways, or mutate the running panel interpreter.

## Consequences

Positive:
- The panel shows provider/model/auth metadata for the exact Hermes version the operator selected.
- Version switching is fast after a cache is warm and deterministic before it is warm.
- Passive metadata loading is side-effect safe.
- Full installs keep the path open for later selected-version OAuth/auth CLI commands.
- Explicit paths make tests, stale-result handling, and concurrent flows easier to reason about.

Costs / trade-offs:
- First use of a Hermes version may be slower because it performs a full install with extras.
- The repo now owns cache lifecycle, readiness sentinels, and rebuild/invalidation logic.
- `uv` becomes a required toolchain dependency.
- The full extras install can fail for dependency reasons that a metadata-only import would have avoided, but failure is explicit and actionable.

## Alternatives Considered

1) Use global `hermes`
- Rejected: introduces version drift between displayed metadata and selected/persisted Hermes version.

2) Install from PyPI
- Rejected: `hermes-agent` is not currently published on PyPI, and `hermes-cli` is unrelated.

3) Install GitHub tag tarballs with `--no-deps`
- Rejected: sufficient for some metadata imports, but not enough for later auth CLI commands.

4) Use an `active` symlink for switching
- Rejected: hidden mutable global state can make stale async workers use the wrong version.

5) Run upstream `install.sh` directly
- Rejected: it performs user-facing install side effects such as config/template writes and symlink creation. The panel should reimplement only the canonical clone/venv/full-install core.

6) Store auth-capable target home under `.cache/`
- Rejected for future auth state: OAuth tokens are durable operator state, not rebuildable cache. The exact auth-home location remains out of scope for this ADR except that passive metadata must use a cache-local isolated home.
