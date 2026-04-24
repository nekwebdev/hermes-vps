"""Server step controller.

Renders the location/server-type/host/admin form, captures user input
with the env-fallback rule (blank inputs preserve previous values), and
validates locally via WizardState.validate_server.

Render-time auto-seeding of location/server_type from loaded options is
preserved to keep behavior identical with the legacy inline path; an
explicit on-options-loaded transition is planned for a later batch.
"""

from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING

from textual.widgets import Checkbox, Input, Label, Select, Static

from scripts.configure_state import choose_seed
from scripts.configure_steps._base import StepController

if TYPE_CHECKING:
    from textual.containers import Vertical


class ServerStepController(StepController):
    key = "server"

    def mount(self, form: "Vertical") -> None:
        provider_name = "Hetzner" if self.state.provider == "hetzner" else "Linode"

        form.mount(Label("Server and SSH profile", classes="section-title"))

        form.mount(Label(f"{provider_name} region", classes="section-title"))
        location_seed = ""
        if self.app.location_options:
            location_seed = choose_seed(
                [item.value for item in self.app.location_options],
                existing=self.state.location,
            )
            self.state.location = location_seed
        location = Select[str](
            options=[
                (item.label, item.value) for item in self.app.location_options
            ],
            allow_blank=False,
            id="location-select",
            value=location_seed if location_seed else Select.BLANK,
        )
        form.mount(location)

        form.mount(Label(f"{provider_name} server type", classes="section-title"))
        server_type_seed = ""
        if self.app.server_type_options:
            preferred = next(
                (
                    item.value
                    for item in self.app.server_type_options
                    if item.recommended
                ),
                "",
            )
            server_type_seed = choose_seed(
                [item.value for item in self.app.server_type_options],
                existing=self.state.server_type,
                preferred=preferred,
            )
            self.state.server_type = server_type_seed
        server_type = Select[str](
            options=[
                (item.label, item.value) for item in self.app.server_type_options
            ],
            allow_blank=False,
            id="server-type-select",
            value=server_type_seed if server_type_seed else Select.BLANK,
        )
        form.mount(server_type)

        form.mount(Label("Hostname", classes="section-title"))
        form.mount(
            Input(
                value="",
                placeholder=self.state.hostname or "Hostname",
                id="hostname-input",
            )
        )

        form.mount(Label("Admin username", classes="section-title"))
        form.mount(
            Input(
                value="",
                placeholder=self.state.admin_username or "Admin username",
                id="admin-user-input",
            )
        )

        form.mount(Label("SSH group", classes="section-title"))
        form.mount(
            Input(
                value="",
                placeholder=self.state.admin_group or "SSH group",
                id="admin-group-input",
            )
        )

        form.mount(Label("SSH private key path", classes="section-title"))
        form.mount(
            Static(self._ssh_key_status_text(), classes="hint", id="ssh-key-status")
        )
        form.mount(
            Checkbox(
                "Ensure 'ssh hermes-vps' alias is present",
                value=self.state.add_ssh_alias,
                id="ssh-alias-toggle",
            )
        )

    def _ssh_key_status_text(self) -> str:
        existing = (
            self.state.original_values.get("BOOTSTRAP_SSH_PRIVATE_KEY_PATH") or ""
        ).strip()
        if existing:
            return f"Present in .env: {existing}"
        planned = self.state.ssh_private_key_path or str(
            pathlib.Path.home() / ".ssh" / "hermes-vps"
        )
        return f"Will be created at apply: {planned}"

    def capture(self) -> bool:
        try:
            self.state.location = (
                self.app.query_one("#location-select", Select).value or ""
            )
            self.state.server_type = (
                self.app.query_one("#server-type-select", Select).value or ""
            )

            hostname_input = self.app.query_one(
                "#hostname-input", Input
            ).value.strip()
            self.state.hostname = (
                hostname_input
                or self.state.hostname
                or (self.state.original_values.get("TF_VAR_hostname", "").strip())
            )

            admin_user_input = self.app.query_one(
                "#admin-user-input", Input
            ).value.strip()
            self.state.admin_username = (
                admin_user_input
                or self.state.admin_username
                or (
                    self.state.original_values.get(
                        "TF_VAR_admin_username", ""
                    ).strip()
                )
            )

            admin_group_input = self.app.query_one(
                "#admin-group-input", Input
            ).value.strip()
            self.state.admin_group = (
                admin_group_input
                or self.state.admin_group
                or (
                    self.state.original_values.get(
                        "TF_VAR_admin_group", ""
                    ).strip()
                )
            )

            self.state.add_ssh_alias = self.app.query_one(
                "#ssh-alias-toggle", Checkbox
            ).value
        except Exception as exc:
            self.app.query_one("#error", Static).update(str(exc))
            return False
        return True

    def validate(self) -> dict[str, str]:
        return self.state.validate_server()
