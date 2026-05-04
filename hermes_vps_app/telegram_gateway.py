from __future__ import annotations

from dataclasses import dataclass
import json
from socket import timeout as SocketTimeout
from typing import Any, Literal, Protocol, final
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen as stdlib_urlopen

TelegramValidationReason = Literal[
    "ok",
    "missing_token",
    "invalid_token",
    "timeout",
    "network",
    "bad_response",
]


class UrlOpenResponse(Protocol):
    def __enter__(self) -> UrlOpenResponse: ...
    def __exit__(self, exc_type: object, exc: object, tb: object) -> object: ...
    def read(self) -> bytes: ...


class UrlOpen(Protocol):
    def __call__(
        self,
        url: str | Request,
        data: bytes | None = None,
        timeout: float | None = None,
    ) -> UrlOpenResponse: ...


@dataclass(frozen=True)
class TelegramGatewayValidationResult:
    ok: bool
    reason: TelegramValidationReason
    summary: str
    bot_username: str = ""
    bot_first_name: str = ""


@final
class TelegramGatewayValidator:
    def __init__(self, *, urlopen: UrlOpen = stdlib_urlopen, timeout: float = 10.0) -> None:
        self._urlopen = urlopen
        self._timeout = timeout

    def validate_bot_token(self, token: str) -> TelegramGatewayValidationResult:
        stripped = token.strip()
        if not stripped:
            return TelegramGatewayValidationResult(
                ok=False,
                reason="missing_token",
                summary="Missing Telegram bot token.",
            )
        request = Request(
            f"https://api.telegram.org/bot{stripped}/getMe",
            headers={"Accept": "application/json"},
            method="GET",
        )
        try:
            with self._urlopen(request, timeout=self._timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 401:
                return TelegramGatewayValidationResult(
                    ok=False,
                    reason="invalid_token",
                    summary="Invalid Telegram bot token.",
                )
            return TelegramGatewayValidationResult(
                ok=False,
                reason="network",
                summary="Unable to reach Telegram API. Please retry.",
            )
        except SocketTimeout:
            return TelegramGatewayValidationResult(
                ok=False,
                reason="timeout",
                summary="Unable to validate Telegram bot token right now (timeout). Please retry.",
            )
        except URLError:
            return TelegramGatewayValidationResult(
                ok=False,
                reason="network",
                summary="Unable to reach Telegram API. Please retry.",
            )
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return TelegramGatewayValidationResult(
                ok=False,
                reason="bad_response",
                summary="Unable to reach Telegram API. Please retry.",
            )

        if not isinstance(payload, dict) or payload.get("ok") is not True:
            return TelegramGatewayValidationResult(
                ok=False,
                reason="bad_response",
                summary="Unable to reach Telegram API. Please retry.",
            )
        result = payload.get("result")
        if not isinstance(result, dict):
            return TelegramGatewayValidationResult(
                ok=False,
                reason="bad_response",
                summary="Unable to reach Telegram API. Please retry.",
            )
        username = _string_value(result.get("username"))
        first_name = _string_value(result.get("first_name"))
        if username:
            summary = f"Telegram gateway is valid: @{username}."
        elif first_name:
            summary = f"Telegram gateway is valid: {first_name}."
        else:
            summary = "Telegram gateway is valid."
        return TelegramGatewayValidationResult(
            ok=True,
            reason="ok",
            summary=summary,
            bot_username=username,
            bot_first_name=first_name,
        )


def _string_value(value: Any) -> str:
    return value if isinstance(value, str) else ""
