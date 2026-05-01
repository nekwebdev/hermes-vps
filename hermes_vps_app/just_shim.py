from __future__ import annotations

import argparse
from typing import cast

from hermes_vps_app import cli

_MIGRATED_WORKFLOWS = {
    "init",
    "init-upgrade",
    "plan",
    "apply",
    "destroy",
    "bootstrap",
    "verify",
    "up",
    "deploy",
}


def _clean_assignment(value: str, *, name: str) -> str:
    stripped = value.strip()
    prefix = f"{name}="
    if stripped.startswith(prefix):
        return stripped[len(prefix) :].strip()
    return stripped


def _provider_from_just(*, provider: str, provider_arg: str) -> str | None:
    """Resolve Just's two historical provider override forms.

    Compatibility glue only: Just supports both `just PROVIDER=linode plan`
    and `just plan PROVIDER=linode`. Validation intentionally remains in the
    headless Python CLI so Just and direct CLI errors share output and status.
    """
    arg_value = _clean_assignment(provider_arg, name="PROVIDER") if provider_arg.strip() else ""
    provider_value = provider.strip()
    if arg_value:
        return arg_value
    if provider_value:
        return provider_value
    return None


def _destroy_confirmed(confirm: str) -> bool:
    return _clean_assignment(confirm, name="CONFIRM") == "YES"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hermes-vps-just-shim")
    _ = parser.add_argument("workflow", choices=sorted(_MIGRATED_WORKFLOWS))
    _ = parser.add_argument("--repo-root", default=".")
    _ = parser.add_argument("--provider", default="")
    _ = parser.add_argument("--provider-arg", default="")
    _ = parser.add_argument("--confirm", default="NO")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    workflow = cast(str, args.workflow)
    repo_root = cast(str, args.repo_root)
    provider_raw = cast(str, args.provider)
    provider_arg = cast(str, args.provider_arg)
    confirm = cast(str, args.confirm)
    provider = _provider_from_just(provider=provider_raw, provider_arg=provider_arg)

    cli_argv = [workflow, "--repo-root", repo_root]
    if provider is not None:
        cli_argv.extend(["--provider", provider])
    if workflow == "destroy":
        # This prompt guard predates the Python CLI and remains Just-only
        # compatibility glue for `just destroy`; operational execution and
        # provider/preflight validation still route through the Python CLI.
        if not _destroy_confirmed(confirm):
            print("WARNING: destroy is destructive and cannot be undone.")
            print("Refusing to continue. Re-run with: just destroy CONFIRM=YES [PROVIDER=linode]")
            return 1
        if provider is not None:
            cli_argv.extend(["--approve-destructive", f"DESTROY:{provider}"])
    return cli.main(cli_argv)


if __name__ == "__main__":
    raise SystemExit(main())
