# pyright: reportAny=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false, reportUnusedCallResult=false, reportUnusedImport=false, reportPrivateUsage=false, reportImplicitStringConcatenation=false, reportImplicitOverride=false, reportIncompatibleMethodOverride=false, reportUnannotatedClassAttribute=false
"""Review step controller.

Renders the diff of staged changes that the user is about to apply.
Pure read-only: no widget capture, no validation, no async work.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.widgets import Label, Static

from scripts.configure_steps._base import StepController

if TYPE_CHECKING:
    from textual.containers import Vertical


class ReviewStepController(StepController):
    key = "review"

    def mount(self, form: "Vertical") -> None:
        form.mount(Label("Review changes before apply", classes="section-title"))
        lines: list[str] = []
        for key, old, new in self.state.recap_rows():
            if key == "SSH_ALIAS":
                lines.append(f"SSH alias: {new or '<empty>'}")
                continue
            lines.append(
                f"{key}: {self._mask_value(key, old)} -> {self._mask_value(key, new)}"
            )
        lines.extend(self._auth_lines())
        if not lines:
            lines.append("No changes to apply.")
        form.mount(Static("\n".join(lines), id="review-diff"))

    @staticmethod
    def _mask_value(key: str, value: str) -> str:
        text = (value or "").strip()
        if not text:
            return "<empty>"
        upper_key = key.upper()
        if "TOKEN" in upper_key or "KEY" in upper_key:
            return "***"
        return text

    def _auth_lines(self) -> list[str]:
        lines: list[str] = []
        original_api_key = (
            self.state.original_values.get("HERMES_API_KEY", "") or ""
        ).strip()
        api_key_was_set = bool(original_api_key)
        api_key_will_be_set = False
        if self.state.hermes_auth_method == "api_key":
            api_key_will_be_set = bool(
                self.state.hermes_api_key_input.strip() or original_api_key
            )

        if api_key_was_set and not api_key_will_be_set:
            lines.append("HERMES_API_KEY: *** -> <empty>")
        elif (not api_key_was_set) and api_key_will_be_set:
            lines.append("HERMES_API_KEY: <empty> -> ***")

        artifact_before = (
            self.state.original_values.get("HERMES_AUTH_ARTIFACT", "") or ""
        ).strip()
        artifact_will_exist = self.state.hermes_auth_method == "oauth"
        artifact_path = str(
            getattr(
                self.orchestrator.hermes,
                "auth_artifact",
                self.app.root_dir / "bootstrap" / "runtime" / "hermes-auth.json",
            )
        )

        if not artifact_before and artifact_will_exist:
            lines.append(f"New Hermes authentication artifact: {artifact_path}")
        elif artifact_before and not artifact_will_exist:
            lines.append(f"Delete Hermes authentication artifact: {artifact_before}")

        return lines
