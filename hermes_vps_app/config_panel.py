from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
from typing import Any, cast, override

from scripts.toolchain_guard import ensure_expected_toolchain_runtime
from scripts.configure_services import (
    CommandRunner,
    ConfigureServiceError,
    ProviderAuthError,
    ProviderService,
)

from hermes_vps_app.cloud_remediation import ProviderId, remediation_for, render_remediation

from hermes_control_core import (
    ActionDescriptor,
    ActionGraph,
    ActionHandler,
    Engine,
    EngineResult,
    RetryPolicy,
    RetryPolicyKind,
    Runner,
)


@dataclass
class ConfigPanelContext:
    values: dict[str, Any]


class ConfigPanelHandler(ActionHandler):
    """Example no-op handler for wiring validation.

    Replace with real implementations that call Runner/InfraPlanner/etc.
    """

    @override
    def run(
        self,
        action: ActionDescriptor,
        context: dict[str, Any],
        runner: Runner,
    ) -> dict[str, Any]:
        if action.action_id == "validate_env":
            ensure_expected_toolchain_runtime()
            repo_root = Path(context.get("repo_root") or ".").resolve()
            env_path = repo_root / ".env"
            env_example_path = repo_root / ".env.example"
            env_exists = env_path.exists()
            env_example_exists = env_example_path.exists()
            if not env_exists and not env_example_exists:
                raise RuntimeError(
                    "Environment files missing: neither .env nor .env.example found. Run configure bootstrap/template step first."
                )
            return {
                "ok": True,
                "toolchain_runtime": "nix_or_docker_nix",
                "repo_root": str(repo_root),
                "env_exists": env_exists,
                "env_example_exists": env_example_exists,
            }

        if action.action_id == "resolve_runner":
            return {"mode": runner.mode}

        if action.action_id == "load_cloud_options":
            values_raw = context.get("values")
            values = cast(dict[str, Any], values_raw) if isinstance(values_raw, dict) else {}
            live_lookup = context.get("live_cloud_lookup") is True
            provider_value = str(values.get("provider") or values.get("TF_VAR_cloud_provider") or "hetzner")
            provider: ProviderId = "linode" if provider_value == "linode" else "hetzner"
            location = str(values.get("location") or values.get("TF_VAR_server_location") or "")

            if not live_lookup:
                return {
                    "live_lookup": False,
                    "provider": provider,
                    "location": location,
                    "regions": ["fsn1", "nbg1"],
                    "types": ["cx22", "cx32"],
                }

            token_key = "HCLOUD_TOKEN" if provider == "hetzner" else "LINODE_TOKEN"
            token = str(values.get(token_key) or "").strip()
            if not token:
                payload = remediation_for(provider, "missing_token")
                raise RuntimeError(render_remediation(payload))

            required_binary = "hcloud" if provider == "hetzner" else "linode-cli"
            if not shutil.which(required_binary):
                payload = remediation_for(provider, "missing_binary")
                raise RuntimeError(render_remediation(payload))

            runner_impl = CommandRunner()
            service = ProviderService(runner_impl)
            try:
                # Strict, minimal read-only auth probe.
                service.auth_probe(provider, token)
            except ProviderAuthError as exc:
                payload = remediation_for(provider, exc.reason, str(exc))
                raise RuntimeError(render_remediation(payload)) from exc

            try:
                # Metadata probe used by this step.
                location_options = service.location_options(provider, token)
                effective_location = location or (
                    location_options[0].value if location_options else ""
                )
                if not effective_location:
                    payload = remediation_for(
                        provider,
                        "metadata_unavailable",
                        "provider returned no locations",
                    )
                    raise RuntimeError(render_remediation(payload))
                server_type_options = service.server_type_options(
                    provider,
                    effective_location,
                    token,
                )
            except ConfigureServiceError as exc:
                payload = remediation_for(provider, "metadata_unavailable", str(exc))
                raise RuntimeError(render_remediation(payload)) from exc

            return {
                "live_lookup": True,
                "provider": provider,
                "location": effective_location,
                "regions": [item.value for item in location_options],
                "types": [item.value for item in server_type_options],
            }

        if action.action_id == "render_review":
            return {"ok": True, "summary": "review generated"}

        return {"ok": True}


def build_example_graph() -> ActionGraph:
    actions = {
        "validate_env": ActionDescriptor(
            action_id="validate_env",
            label="Validate environment",
            side_effect_level="none",
            retry_policy=RetryPolicy(kind=RetryPolicyKind.NONE, max_attempts=1),
        ),
        "resolve_runner": ActionDescriptor(
            action_id="resolve_runner",
            label="Resolve runner",
            deps=["validate_env"],
            side_effect_level="none",
            retry_policy=RetryPolicy(kind=RetryPolicyKind.NONE, max_attempts=1),
        ),
        "load_cloud_options": ActionDescriptor(
            action_id="load_cloud_options",
            label="Load cloud options",
            deps=["resolve_runner"],
            side_effect_level="none",
            retry_policy=RetryPolicy(kind=RetryPolicyKind.FIXED, max_attempts=2, delay_seconds=0),
        ),
        "render_review": ActionDescriptor(
            action_id="render_review",
            label="Render review",
            deps=["load_cloud_options"],
            side_effect_level="none",
            retry_policy=RetryPolicy(kind=RetryPolicyKind.NONE, max_attempts=1),
        ),
    }
    return ActionGraph(name="config_panel_example", actions=actions)


def run_example_config_panel(
    runner: Runner,
    values: dict[str, Any] | None = None,
    live_cloud_lookup: bool = False,
) -> EngineResult:
    graph = build_example_graph()
    handler = ConfigPanelHandler()
    engine = Engine(
        graph=graph,
        runner=runner,
        handler=handler,
        context={
            "values": values or {},
            "repo_root": str(Path(".").resolve()),
            "live_cloud_lookup": live_cloud_lookup,
        },
    )
    return engine.run()
