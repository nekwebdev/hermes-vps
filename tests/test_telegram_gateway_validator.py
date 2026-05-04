from __future__ import annotations

from dataclasses import dataclass
from socket import timeout as SocketTimeout
from typing import Any, cast
from urllib.error import HTTPError, URLError

from hermes_vps_app.telegram_gateway import TelegramGatewayValidator


@dataclass
class FakeResponse:
    payload: bytes

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


def test_get_me_success_returns_bot_username_without_exposing_token_url() -> None:
    calls: list[tuple[object, object, float | None]] = []

    def fake_urlopen(url: object, data: object = None, timeout: float | None = None) -> FakeResponse:
        calls.append((url, data, timeout))
        return FakeResponse(b'{"ok":true,"result":{"username":"hermes_bot","first_name":"Hermes"}}')

    result = TelegramGatewayValidator(urlopen=fake_urlopen, timeout=7.5).validate_bot_token("123:SECRET")

    assert result.ok is True
    assert result.reason == "ok"
    assert result.bot_username == "hermes_bot"
    assert result.bot_first_name == "Hermes"
    assert result.summary == "Telegram gateway is valid: @hermes_bot."
    assert calls[0][1] is None
    assert calls[0][2] == 7.5
    assert "123:SECRET" not in repr(result)


def test_get_me_maps_unauthorized_to_invalid_token_without_raw_api_detail() -> None:
    def fake_urlopen(url: object, data: object = None, timeout: float | None = None) -> FakeResponse:
        raise HTTPError("https://api.telegram.org/bot123:SECRET/getMe", 401, "Unauthorized", cast(Any, {}), None)

    result = TelegramGatewayValidator(urlopen=fake_urlopen).validate_bot_token("123:SECRET")

    assert result.ok is False
    assert result.reason == "invalid_token"
    assert result.summary == "Invalid Telegram bot token."
    assert "Unauthorized" not in result.summary
    assert "123:SECRET" not in repr(result)


def test_get_me_maps_timeout_and_network_to_terse_operator_copy() -> None:
    def timeout_urlopen(url: object, data: object = None, timeout: float | None = None) -> FakeResponse:
        raise SocketTimeout("timed out")

    timeout_result = TelegramGatewayValidator(urlopen=timeout_urlopen).validate_bot_token("123:SECRET")
    assert timeout_result.reason == "timeout"
    assert timeout_result.summary == "Unable to validate Telegram bot token right now (timeout). Please retry."

    def network_urlopen(url: object, data: object = None, timeout: float | None = None) -> FakeResponse:
        raise URLError("temporary failure")

    network_result = TelegramGatewayValidator(urlopen=network_urlopen).validate_bot_token("123:SECRET")
    assert network_result.reason == "network"
    assert network_result.summary == "Unable to reach Telegram API. Please retry."


def test_get_me_handles_bad_json_as_bad_response() -> None:
    def fake_urlopen(url: object, data: object = None, timeout: float | None = None) -> FakeResponse:
        return FakeResponse(b'not-json')

    result = TelegramGatewayValidator(urlopen=fake_urlopen).validate_bot_token("123:SECRET")

    assert result.ok is False
    assert result.reason == "bad_response"
    assert result.summary == "Unable to reach Telegram API. Please retry."
