#!/usr/bin/env python3
# pyright: reportAny=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false, reportUnusedCallResult=false, reportUnusedImport=false, reportPrivateUsage=false, reportImplicitStringConcatenation=false, reportImplicitOverride=false, reportIncompatibleMethodOverride=false, reportUnannotatedClassAttribute=false
from __future__ import annotations

import argparse
import pathlib
import re
from collections.abc import Iterable

_SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[.-][0-9A-Za-z]+)*$")
_RELEASE_TAG_RE = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+(?:[.-][0-9A-Za-z]+)*$")
_ALLOWLIST_RE = re.compile(r"^-?[0-9]+(?:,-?[0-9]+)*$")


def _read_text(path: pathlib.Path) -> str:
    return path.read_text() if path.exists() else ""


def get_env_value(path: str | pathlib.Path, key: str) -> str:
    content = _read_text(pathlib.Path(path))
    match = re.search(rf"^{re.escape(key)}=(.*)$", content, re.MULTILINE)
    return match.group(1) if match else ""


def set_env_value(path: str | pathlib.Path, key: str, value: str) -> None:
    file_path = pathlib.Path(path)
    content = _read_text(file_path)
    line = f"{key}={value}"
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    if pattern.search(content):
        content = pattern.sub(line, content, count=1)
    else:
        if content and not content.endswith("\n"):
            content += "\n"
        content += line + "\n"
    file_path.write_text(content)


def server_image_for_provider(provider: str) -> str:
    mapping = {
        "linode": "linode/debian13",
        "hetzner": "debian-13",
    }
    if provider not in mapping:
        raise ValueError(f"unsupported provider for server image mapping: {provider}")
    return mapping[provider]


def is_valid_semver(value: str) -> bool:
    return bool(_SEMVER_RE.fullmatch(value))


def is_valid_release_tag(value: str) -> bool:
    return bool(_RELEASE_TAG_RE.fullmatch(value))


def release_tag_for_version(version: str) -> str:
    if not is_valid_semver(version):
        return ""
    return f"v{version}"


def is_valid_telegram_allowlist(value: str) -> bool:
    return bool(_ALLOWLIST_RE.fullmatch(value))


def choose_seed(options: Iterable[str], existing: str = "", preferred: str = "") -> str:
    values = list(options)
    if not values:
        raise ValueError("options must not be empty")
    if existing and existing in values:
        return existing
    if preferred and preferred in values:
        return preferred
    return values[0]


def rotate_to_seed(options: Iterable[str], seed: str) -> list[str]:
    values = list(options)
    if not values or seed not in values:
        return values
    idx = values.index(seed)
    return values[idx:] + values[:idx]


def _cli() -> int:
    parser = argparse.ArgumentParser(description="configure logic helper")
    sub = parser.add_subparsers(dest="cmd", required=True)

    get_cmd = sub.add_parser("env-get")
    get_cmd.add_argument("path")
    get_cmd.add_argument("key")

    set_cmd = sub.add_parser("env-set")
    set_cmd.add_argument("path")
    set_cmd.add_argument("key")
    set_cmd.add_argument("value")

    image_cmd = sub.add_parser("server-image")
    image_cmd.add_argument("provider")

    semver_cmd = sub.add_parser("is-semver")
    semver_cmd.add_argument("value")

    release_cmd = sub.add_parser("is-release-tag")
    release_cmd.add_argument("value")

    allow_cmd = sub.add_parser("is-telegram-allowlist")
    allow_cmd.add_argument("value")

    args = parser.parse_args()

    if args.cmd == "env-get":
        print(get_env_value(args.path, args.key))
        return 0
    if args.cmd == "env-set":
        set_env_value(args.path, args.key, args.value)
        return 0
    if args.cmd == "server-image":
        print(server_image_for_provider(args.provider))
        return 0
    if args.cmd == "is-semver":
        return 0 if is_valid_semver(args.value) else 1
    if args.cmd == "is-release-tag":
        return 0 if is_valid_release_tag(args.value) else 1
    if args.cmd == "is-telegram-allowlist":
        return 0 if is_valid_telegram_allowlist(args.value) else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(_cli())
