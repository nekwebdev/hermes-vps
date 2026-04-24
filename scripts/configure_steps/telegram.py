"""Telegram step controller.

Owns the bot-token + allowlist form, post-mount placeholder/title sync,
and widget capture. Runtime validation (the curl-based getMe call) lives
in the orchestrator and is dispatched by ConfigureTUI.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.css.query import NoMatches
from textual.widgets import Input, Label, Static

from scripts.configure_steps._base import StepController

if TYPE_CHECKING:
    from textual.containers import Vertical


class TelegramStepController(StepController):
    key = "telegram"

    def mount(self, form: "Vertical") -> None:
        form.mount(Label("How to get telegram token", classes="section-title"))
        form.mount(
            Static(
                "1) Open https://web.telegram.org/k/#@BotFather and chat with @BotFather",
                classes="hint",
            )
        )
        form.mount(Static("2) Run /newbot and follow prompts", classes="hint"))
        form.mount(Static("3) Copy bot token from BotFather", classes="hint"))

        form.mount(
            Label(
                "Telegram bot token",
                classes="section-title",
                id="telegram-token-title",
            )
        )
        form.mount(Input(password=True, id="telegram-token-input"))

        form.mount(Label("How to get Telegram ID", classes="section-title"))
        form.mount(
            Static(
                "1) Open https://web.telegram.org/k/#@userinfobot (or https://web.telegram.org/k/#@RawDataBot)",
                classes="hint",
            )
        )
        form.mount(
            Static(
                "2) Send any message, then copy numeric user id(s) (you can use multiple comma-separated IDs)",
                classes="hint",
            )
        )

        form.mount(Label("Telegram allowlist IDs", classes="section-title"))
        form.mount(
            Input(
                value=self.state.telegram_allowlist_ids,
                placeholder="12345,-100987654321",
                id="telegram-allowlist-input",
            )
        )
        self._refresh_token_ui()

    def _refresh_token_ui(self) -> None:
        try:
            token_present = self.orchestrator.telegram_token_present()
            replace_effective = (not token_present) or bool(
                self.state.telegram_bot_token_input
            )
            self.state.telegram_bot_token_replace = replace_effective

            title = self.app.query_one("#telegram-token-title", Label)
            token_input = self.app.query_one("#telegram-token-input", Input)

            if token_present:
                title.update("Existing Telegram bot token")
                token_input.placeholder = (
                    "Paste new TELEGRAM_BOT_TOKEN to replace current one"
                )
            else:
                title.update("Enter Telegram bot token")
                token_input.placeholder = "Paste TELEGRAM_BOT_TOKEN"
        except NoMatches:
            return

    def capture(self) -> bool:
        try:
            token_present = self.orchestrator.telegram_token_present()
            self.state.telegram_bot_token_input = self.app.query_one(
                "#telegram-token-input", Input
            ).value.strip()
            self.state.telegram_bot_token_replace = (not token_present) or bool(
                self.state.telegram_bot_token_input
            )
            self.state.telegram_allowlist_ids = self.app.query_one(
                "#telegram-allowlist-input", Input
            ).value.strip()
        except Exception as exc:
            self.app.query_one("#error", Static).update(str(exc))
            return False
        return True

    def validate(self) -> dict[str, str]:
        return self.state.validate_telegram()
