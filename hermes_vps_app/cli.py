# pyright: reportAny=false, reportUnusedCallResult=false, reportUnreachable=false
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hermes_control_core import RunnerFactory, SessionAuditLog

from hermes_vps_app.operational import (
    build_destroy_preview,
    build_graph,
    resolve_provider,
    run_monitoring_graph,
    run_operational_graph,
    validate_init_environment,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hermes-vps")
    sub = parser.add_subparsers(dest="action", required=True)

    for action_name in ("init", "init-upgrade", "plan", "apply", "destroy", "bootstrap", "verify", "up", "deploy"):
        action_p = sub.add_parser(action_name)
        action_p.add_argument("--repo-root", default=".")
        action_p.add_argument("--provider", choices=["hetzner", "linode"], default=None)
        action_p.add_argument("--allow-host-override", action="store_true")
        action_p.add_argument("--override-reason", default="")
        action_p.add_argument("--host-override-token", default=None)
        action_p.add_argument("--approve-destructive", default=None)

    monitoring_p = sub.add_parser("monitoring")
    monitoring_p.add_argument("--repo-root", default=".")
    monitoring_p.add_argument("--provider", choices=["hetzner", "linode"], default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.action in {"init", "init-upgrade", "plan", "apply", "destroy", "bootstrap", "verify", "up", "deploy"}:
        repo_root = Path(args.repo_root).resolve()
        factory = RunnerFactory(
            repo_root=repo_root,
            allow_host_override=args.allow_host_override,
            override_reason=args.override_reason,
        )
        runner = factory.get()
        audit_log = SessionAuditLog(session_id=f"{args.action}-{repo_root.name}", repo_root=repo_root)

        approval_token = args.approve_destructive
        confirmation_mode = "headless"
        if args.action == "destroy":
            provider = resolve_provider(provider_override=args.provider)
            selection = validate_init_environment(repo_root=repo_root, provider=provider)
            preview = build_destroy_preview(repo_root=repo_root, provider=provider, tf_dir=selection.tf_dir, runner=runner)
            print(f"Destroy preview: provider={preview.provider}")
            print(f"Destroy preview: tf_dir={preview.tf_dir}")
            print(f"Destroy preview: backup_root={preview.backup_root} backup_dir={preview.backup_dir}")
            print(f"Destroy preview: state_files={len(preview.state_files)}")
            for state_file in preview.state_files:
                print(f"  - {state_file}")
            if preview.safe_outputs:
                print("Destroy preview: safe_outputs")
                for key, value in sorted(preview.safe_outputs.items()):
                    print(f"  - {key}={value}")
            if approval_token is None and sys.stdin.isatty():
                confirmation_mode = "interactive"
                typed = input(f"Type DESTROY {provider} to confirm: ").strip()
                if typed == f"DESTROY {provider}":
                    approval_token = f"DESTROY:{provider}"

        result = run_operational_graph(
            action=args.action,
            runner=runner,
            repo_root=repo_root,
            provider_override=args.provider,
            host_override_token=args.host_override_token,
            approve_destructive=approval_token,
            confirmation_mode=confirmation_mode,
            audit_log=audit_log,
        )
        if not result.completed:
            graph = build_graph(args.action)
            failed_action_id = next((aid for aid, state in result.states.items() if state.last_error), None)
            if failed_action_id is None:
                raise RuntimeError(f"{args.action} graph failed")
            failed_state = result.states[failed_action_id]
            descriptor = graph.actions[failed_action_id]
            repair_scope = descriptor.repair_hint or "rerun full panel"
            status = failed_state.status.value
            detail = failed_state.last_error or f"{args.action} graph failed"
            raise RuntimeError(
                f"action={failed_action_id} status={status} repair_scope={repair_scope} error={detail}"
            )
        return 0

    if args.action == "monitoring":
        repo_root = Path(args.repo_root).resolve()
        _ = run_monitoring_graph(repo_root=repo_root, provider_override=args.provider)
        return 0

    parser.error(f"unsupported action: {args.action}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
