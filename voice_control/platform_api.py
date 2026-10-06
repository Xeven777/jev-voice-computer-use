"""Platform abstraction: Windows vs Linux.

goal.py already takes observe/act callables; this module formalises the
signatures so app.py / app_linux.py / goal_eval can swap backends via env:

    JEV_PLATFORM=linux  (default on Linux) | windows (default on Windows)
"""
from __future__ import annotations

import os
import sys
from typing import Any, Callable, Protocol

from .core import Control

# observe(hwnd) -> (state, controls); act(verb, target, ...) -> message
Observe = Callable[[Any], tuple[dict[str, Any], list[Control]]]
Act = Callable[..., str]


class PlatformBackend(Protocol):
    name: str

    def capture(self, hwnd: Any = None, max_nodes: int = 3000) -> tuple[dict[str, Any], list[Control]]: ...
    def capture_settled(self, hwnd: Any = None, sparse: int = 12, timeout_s: float = 4.0) -> tuple[dict[str, Any], list[Control]]: ...
    def execute(self, verb: str, target: dict[str, Any], state: dict[str, Any], controls: list[Control],
                apps: list[dict[str, str]], utterance: str, app_hwnd: Any = None,
                text: str | None = None) -> str: ...
    def open_windows(self) -> list[dict[str, Any]]: ...
    def installed_apps(self) -> list[dict[str, str]]: ...
    def window_app(self, hwnd: Any, size: int, background: str) -> tuple[str, Any]: ...
    def settle(self, verb: str, before: tuple, timeout_s: float = 3.0) -> int: ...


def default_platform() -> str:
    forced = os.environ.get("JEV_PLATFORM", "").strip().lower()
    if forced in ("linux", "windows"):
        return forced
    return "windows" if sys.platform.startswith("win") else "linux"


def load_backend(name: str = "") -> PlatformBackend:
    name = (name or default_platform()).lower()
    if name == "linux":
        from .platforms.linux import backend as linux_backend
        return linux_backend
    from . import windows as windows_backend  # type: ignore
    return windows_backend  # type: ignore
