# pyright: reportAny=false, reportUnusedCallResult=false, reportUnreachable=false
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hermes_control_core import RunnerFactory, SessionAuditLog

from hermes_vps_app.error_taxonomy import classify_exception, raise_graph_failure
from hermes_vps_app.operational import (
    build_destroy_preview,
    build_graph,
    build_monitoring_graph,
    resolve_provider,
    run_monitoring_graph,
    run_operational_graph,
    validate_init_environment,
)
from hermes_vps_app.status_presentation import (
    presentation_from_engine_result,
    presentation_from_monitoring_payload,
    preview_from_graph,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hermes-vps")
    sub = parser.add_subparsers(dest="action", required=True)

    for action_name in ("init", "init-upgrade", "plan", "apply", "destroy", "bootstrap", "verify", "up", "deploy"):
        action_p = sub.add_parser(action_name)
        action_p.add_argument("--repo-root", default=".")
        action_p.add_argument("--provider", default=None)
        action_p.add_argument("--allow-host-override", action="store_true")
        action_p.add_argument("--override-reason", default="")
        action_p.add_argument("--host-override-token", default=None)
        action_p.add_argument("--approve-destructive", default=None)
        action_p.add_argument("--output", choices=["human", "json"], default="human")
        action_p.add_argument("--preview", action="store_true")

    monitoring_p = sub.add_parser("monitoring")
    monitoring_p.add_argument("--repo-root", default=".")
    monitoring_p.add_argument("--provider", default=None)
    monitoring_p.add_argument("--output", choices=["human", "json"], default="human")

    panel_p = sub.add_parser("panel")
    panel_p.add_argument("--repo-root", default=".")
    panel_p.add_argument("--advanced-unsafe-environment", action="store_true")
    panel_p.add_argument("--allow-host-override", action="store_true")
    panel_p.add_argument("--override-reason", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.action == "panel":
        from hermes_vps_app import panel_entrypoint

        panel_args = ["--repo-root", args.repo_root]
        if args.advanced_unsafe_environment:
            panel_args.append("--advanced-unsafe-environment")
        if args.allow_host_override:
            panel_args.append("--allow-host-override")
        if args.override_reason:
            panel_args.extend(["--override-reason", args.override_reason])
        return panel_entrypoint.main(panel_args)

    if args.action in {"init", "init-upgrade", "plan", "apply", "destroy", "bootstrap", "verify", "up", "deploy"}:
        try:
            repo_root = Path(args.repo_root).resolve()
            audit_log = SessionAuditLog(session_id=f"{args.action}-{repo_root.name}", repo_root=repo_root)
            factory = RunnerFactory(
                repo_root=repo_root,
                allow_host_override=args.allow_host_override,
                override_reason=args.override_reason,
                audit_log=audit_log,
            )
            runner = factory.get()
            host_override_preflight_line = ""
            if runner.mode == "host" and args.host_override_token and args.host_override_token.strip() == "I-ACK-HOST-OVERRIDE":
                reason = args.override_reason.strip()
                host_override_preflight_line = f"host_override: approved=true runner=host reason={reason}"

            graph = build_graph(args.action)
            if args.preview:
                provider = resolve_provider(provider_override=args.provider)
                selection = validate_init_environment(repo_root=repo_root, provider=provider)
                destroy_preview_payload: dict[str, object] | None = None
                if args.action == "destroy":
                    destroy_preview = build_destroy_preview(
                        repo_root=repo_root,
                        provider=provider,
                        tf_dir=selection.tf_dir,
                        runner=runner,
                    )
                    destroy_preview_payload = {
                        "provider": destroy_preview.provider,
                        "tf_dir": str(destroy_preview.tf_dir),
                        "backup_root": str(destroy_preview.backup_root),
                        "backup_dir": str(destroy_preview.backup_dir),
                        "state_files": [str(path) for path in destroy_preview.state_files],
                        "state_file_count": len(destroy_preview.state_files),
                        "safe_outputs": dict(destroy_preview.safe_outputs),
                    }
                presentation = preview_from_graph(
                    workflow=args.action,
                    graph=graph,
                    provider=provider,
                    runner_mode=runner.mode,
                    destroy_preview=destroy_preview_payload,
                )
                if args.output == "json":
                    print(presentation.to_json())
                else:
                    if host_override_preflight_line:
                        print(host_override_preflight_line)
                    for line in presentation.to_human_lines():
                        print(line)
                return 0

            approval_token = args.approve_destructive
            confirmation_mode = "headless"
            if args.action == "destroy":
                provider = resolve_provider(provider_override=args.provider)
                selection = validate_init_environment(repo_root=repo_root, provider=provider)
                preview = build_destroy_preview(repo_root=repo_root, provider=provider, tf_dir=selection.tf_dir, runner=runner)
                preview_payload: dict[str, object] = {
                    "provider": preview.provider,
                    "tf_dir": str(preview.tf_dir),
                    "backup_root": str(preview.backup_root),
                    "backup_dir": str(preview.backup_dir),
                    "state_files": [str(path) for path in preview.state_files],
                    "state_file_count": len(preview.state_files),
                    "safe_outputs": dict(preview.safe_outputs),
                }
                if args.output == "human":
                    destroy_presentation = preview_from_graph(
                        workflow=args.action,
                        graph=graph,
                        provider=provider,
                        runner_mode=runner.mode,
                        destroy_preview=preview_payload,
                    )
                    for line in destroy_presentation.to_human_lines():
                        print(line)
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
                override_reason=args.override_reason,
                approve_destructive=approval_token,
                confirmation_mode=confirmation_mode,
                audit_log=audit_log,
            )
            if not result.completed:
                raise_graph_failure(result=result, graph=graph, workflow=args.action)
            presentation = presentation_from_engine_result(
                workflow=args.action,
                graph=graph,
                result=result,
            )
            if args.output == "json":
                print(presentation.to_json())
            else:
                if host_override_preflight_line:
                    print(host_override_preflight_line)
                for line in presentation.to_human_lines():
                    print(line)
            return 0
        except Exception as exc:
            error = classify_exception(exc, workflow=args.action)
            if args.output == "json":
                print(error.to_json())
            else:
                for line in error.to_human_lines():
                    print(line, file=sys.stderr)
            return error.exit_code

    if args.action == "monitoring":
        try:
            repo_root = Path(args.repo_root).resolve()
            payload = run_monitoring_graph(repo_root=repo_root, provider_override=args.provider)
            presentation = presentation_from_monitoring_payload(graph=build_monitoring_graph(), payload=payload)
            if args.output == "json":
                print(presentation.to_json())
            else:
                for line in presentation.to_human_lines():
                    print(line)
            return 0
        except Exception as exc:
            error = classify_exception(exc, workflow=args.action)
            if args.output == "json":
                print(error.to_json())
            else:
                for line in error.to_human_lines():
                    print(line, file=sys.stderr)
            return error.exit_code

    parser.error(f"unsupported action: {args.action}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
