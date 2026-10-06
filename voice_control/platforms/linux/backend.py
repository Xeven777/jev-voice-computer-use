"""Linux backend: wires atspi/screen/execute/apps into the platform API."""
from __future__ import annotations

from typing import Any

from ...core import Control
from . import apps, atspi, screen
from .execute import execute as _execute_impl

name = "linux"


def capture(hwnd: Any = None, max_nodes: int = 3000):
    return atspi.capture(hwnd, max_nodes)


def capture_settled(hwnd: Any = None, sparse: int = 12, timeout_s: float = 4.0):
    import time
    from ...uia_watch import LOADING_NAME
    state, controls = capture(hwnd)
    wid = state["activeWindow"]["wid"]
    known = set(state.get("loading", []))
    deadline = time.monotonic() + timeout_s
    stable = 0  # consecutive re-reads with no new controls and no loading signs
    while time.monotonic() < deadline:
        appeared = [x for x in state.get("loading", []) if x not in known]
        # Before, only 12+ controls broke the loop: on windows exposing fewer
        # (a bare terminal, an Electron app), every look rescanned ~10 times
        # until the deadline. A still screen is settled too.
        if not appeared and (len(controls) >= sparse or stable >= 2):
            break
        time.sleep(0.3 if appeared else 0.4)
        again, more = capture(wid)
        if len(more) > len(controls) or appeared:
            stable = 0
        else:
            stable += 1
        if appeared or len(more) >= len(controls):
            state, controls = again, more
    return state, controls


def execute(verb: str, target: dict, state: dict, controls: list,
            app_list: list, utterance: str, app_hwnd: Any = None,
            text: str | None = None) -> str:
    return _execute_impl(verb, target, state, controls, app_list,
                         utterance, app_hwnd, text)


def open_windows():
    return screen.open_windows()


def installed_apps():
    return apps.installed_apps()


def window_app(hwnd: Any, size: int, background: str):
    title = screen.window_name(int(hwnd))
    return (title or "app", None)


def settle(verb: str, before: tuple, timeout_s: float = 3.0) -> int:
    return screen.settle(verb, before, timeout_s)
