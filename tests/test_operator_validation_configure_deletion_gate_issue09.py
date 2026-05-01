from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = REPO_ROOT / "docs" / "operator-validation-configure-deletion.md"
ISSUE_PATH = (
    REPO_ROOT
    / ".scratch"
    / "panel-native-operator-experience"
    / "issues"
    / "09-operator-validation-and-old-configure-deletion-gate.md"
)
JUSTFILE_PATH = REPO_ROOT / "Justfile"
OLD_CONFIGURE_PATH = REPO_ROOT / "scripts" / "configure_tui.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_operator_validation_gate_documents_required_regression_and_manual_checks() -> None:
    doc = _read(DOC_PATH)
    issue = _read(ISSUE_PATH)

    assert "Status: completed" in issue
    assert "docs/operator-validation-configure-deletion.md" in issue

    required_regression_phrases = [
        "Missing `.env`",
        "Existing `.env`",
        "Keep-existing secrets",
        "Provider switch dependency review",
        "Live lookup remediation",
        "Stale async validation",
        "Atomic write",
        "Secret-safe previews",
    ]
    required_manual_phrases = [
        "Fresh repo",
        "Existing Hetzner config",
        "Existing Linode config if feasible",
        "Bad permissions remediation",
        "Token keep path",
        "Token replace path",
    ]
    required_gate_phrases = [
        "deletion blocked",
        "No explicit HITL approval is recorded",
        "temporary source material",
        "scripts/configure_tui.py",
        "HITL approval",
        "Old configure implementation remains intact",
        "not approved",
    ]

    for phrase in required_regression_phrases + required_manual_phrases + required_gate_phrases:
        assert phrase in doc
        assert phrase in issue


def test_operator_validation_gate_verifies_configure_and_panel_route_to_same_app() -> None:
    doc = _read(DOC_PATH)
    justfile = _read(JUSTFILE_PATH)

    assert OLD_CONFIGURE_PATH.exists(), "old configure code must remain intact until HITL approval"

    assert "panel:" in justfile
    assert "configure:" in justfile
    assert "python3 -m hermes_vps_app.panel_entrypoint --repo-root ." in justfile
    assert (
        "python3 -m hermes_vps_app.panel_entrypoint --repo-root . --initial-panel configuration"
        in justfile
    )

    assert "`just panel` must launch `python3 -m hermes_vps_app.panel_entrypoint --repo-root .`" in doc
    expected_configure_route = (
        "`just configure` must launch the same app, "
        + "`python3 -m hermes_vps_app.panel_entrypoint --repo-root . --initial-panel configuration`"
    )
    assert expected_configure_route in doc
    assert "both commands must route into the same Textual control panel application" in doc
