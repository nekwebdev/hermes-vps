from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
GUIDE_PATH = REPO_ROOT / "docs" / "control-panel-operator-guide.md"
README_PATH = REPO_ROOT / "README.md"
ISSUE_PATH = (
    REPO_ROOT
    / ".scratch"
    / "control-panel-v2-hardening-docs-cutover"
    / "issues"
    / "12-operator-docs-cutover-guide-for-migrated-control-panel-workflows.md"
)


def test_issue12_operator_cutover_guide_documents_migrated_control_panel_workflows() -> None:
    guide = GUIDE_PATH.read_text(encoding="utf-8")
    readme = README_PATH.read_text(encoding="utf-8")
    issue = ISSUE_PATH.read_text(encoding="utf-8")

    assert "docs/control-panel-operator-guide.md" in readme
    assert "Status: completed" in issue

    required_phrases = [
        "python3 -m scripts.configure_tui",
        "python3 -m hermes_vps_app.cli init --repo-root .",
        "python3 -m hermes_vps_app.cli init-upgrade --repo-root .",
        "python3 -m hermes_vps_app.cli plan --repo-root .",
        "python3 -m hermes_vps_app.cli apply --repo-root .",
        "python3 -m hermes_vps_app.cli bootstrap --repo-root .",
        "python3 -m hermes_vps_app.cli verify --repo-root .",
        "python3 -m hermes_vps_app.cli destroy --repo-root . --preview",
        "python3 -m hermes_vps_app.cli up --repo-root .",
        "python3 -m hermes_vps_app.cli deploy --repo-root .",
        "python3 -m hermes_vps_app.cli monitoring --repo-root .",
        "--provider linode",
        "--output json",
        "graph preview",
        "exit code taxonomy",
        "direnv_nix",
        "nix_develop",
        "docker_nix",
        "host",
        "per-launch",
        "no silent host fallback",
        "I-ACK-HOST-OVERRIDE",
        "DESTROY:<provider>",
        ".state-backups/<provider>/",
        "audit metadata example",
        "just plan PROVIDER=linode",
        "python3 -m hermes_vps_app.just_shim plan",
        "docs cutover checklist",
        "Justfile removal requires a separate HITL issue",
    ]
    for phrase in required_phrases:
        assert phrase in guide
