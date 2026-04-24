#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class ToolchainRuntime:
    python_executable: str
    python_path: str
    shell_path: str


def current_runtime() -> ToolchainRuntime:
    return ToolchainRuntime(
        python_executable=sys.executable,
        python_path=os.environ.get("PATH", ""),
        shell_path=shutil.which("python3") or "",
    )


def is_expected_toolchain_runtime(runtime: ToolchainRuntime | None = None) -> bool:
    rt = runtime or current_runtime()
    return rt.python_executable.startswith("/nix/store/") and "/nix/store/" in rt.python_path


def ensure_expected_toolchain_runtime() -> None:
    runtime = current_runtime()
    if is_expected_toolchain_runtime(runtime):
        return

    raise RuntimeError(
        "configure runtime isolation check failed: Python must run inside nix/docker dev toolchain. "
        f"sys.executable={runtime.python_executable!r} PATH={runtime.python_path!r} which(python3)={runtime.shell_path!r}"
    )
