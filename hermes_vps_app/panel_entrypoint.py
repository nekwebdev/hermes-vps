# pyright: reportAny=false, reportUnusedCallResult=false
from __future__ import annotations

import argparse
from pathlib import Path

from hermes_control_core import RunnerFactory, SessionAuditLog

from hermes_vps_app.panel_startup import PanelStartupState, evaluate_panel_startup
from hermes_vps_app.panel_shell import ControlPanelShell, InitialPanel
from hermes_vps_app.panel_textual_app import HermesControlPanelApp, render_panel_text

__all__ = ["HermesControlPanelApp", "build_parser", "main"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hermes-vps-panel")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--initial-panel",
        choices=("configuration", "deployment", "maintenance", "monitoring"),
        default="deployment",
    )
    parser.add_argument("--advanced-unsafe-environment", action="store_true")
    parser.add_argument("--allow-host-override", action="store_true")
    parser.add_argument("--override-reason", default="")
    parser.add_argument(
        "--headless-render",
        action="store_true",
        help="render deterministic panel text instead of starting the interactive Textual app",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.allow_host_override and not args.advanced_unsafe_environment:
        print(
            "Host override is hidden behind the advanced unsafe environment path; "
            + "rerun with --advanced-unsafe-environment --allow-host-override --override-reason <reason>."
        )
        return 2
    if args.allow_host_override and not args.override_reason.strip():
        print("Host override requires --override-reason with a non-empty audited reason.")
        return 2
    repo_root = Path(args.repo_root).resolve()
    audit_log = SessionAuditLog(session_id=f"panel-{repo_root.name}", repo_root=repo_root)
    runner_factory = RunnerFactory(
        repo_root=repo_root,
        allow_host_override=args.allow_host_override,
        override_reason=args.override_reason,
        audit_log=audit_log,
    )
    result = evaluate_panel_startup(repo_root=repo_root, runner_factory=runner_factory)
    initial_panel: InitialPanel = args.initial_panel

    # Instantiate the shell on the successful Python panel entrypoint path so the
    # locked startup result is exposed to the app layer without delegating to the
    # legacy configure TUI.
    shell = ControlPanelShell(startup_result=result, initial_panel=initial_panel)

    if args.headless_render:
        print(
            render_panel_text(
                shell=shell,
                repo_root=repo_root,
                startup_result=result,
                initial_panel=initial_panel,
                host_override_reason=args.override_reason.strip() if args.allow_host_override else None,
            )
        )
    else:
        app = HermesControlPanelApp(
            shell=shell,
            repo_root=repo_root,
            startup_result=result,
            initial_panel=initial_panel,
        )
        app.run()

    if result.state is PanelStartupState.BLOCKED:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
