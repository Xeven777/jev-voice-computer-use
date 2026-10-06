"""Linux input + window ops via xdotool (X11). Wayland gets a new backend later."""
from __future__ import annotations

import os
import subprocess
import time

DEBUG = os.environ.get("JEV_DEBUG", "1") not in ("0", "", "false")


def _run(*args: str, timeout: float = 10.0) -> str:
    if DEBUG:
        print(f"  $ {' '.join(args)}", flush=True)
    out = subprocess.run(list(args), capture_output=True, text=True, timeout=timeout)
    if out.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed: {out.stderr.strip()[:200]}")
    return out.stdout


def click(x: int, y: int, button: int = 1) -> None:
    _run("xdotool", "mousemove", str(x), str(y), "click", str(button))
    time.sleep(0.15)


def double_click(x: int, y: int) -> None:
    _run("xdotool", "mousemove", str(x), str(y), "click", "--repeat", "2", "--delay", "80", "1")
    time.sleep(0.2)


def right_click(x: int, y: int) -> None:
    click(x, y, button=3)


def hover(x: int, y: int) -> None:
    _run("xdotool", "mousemove", str(x), str(y))
    time.sleep(0.1)


def scroll_up(n: int = 3) -> None:
    for _ in range(n):
        _run("xdotool", "click", "4")
        time.sleep(0.05)


def scroll_down(n: int = 3) -> None:
    for _ in range(n):
        _run("xdotool", "click", "5")
        time.sleep(0.05)


def scroll_left(n: int = 3) -> None:
    for _ in range(n):
        _run("xdotool", "click", "6")
        time.sleep(0.05)


def scroll_right(n: int = 3) -> None:
    for _ in range(n):
        _run("xdotool", "click", "7")
        time.sleep(0.05)


def type_text(text: str, gap_ms: int = 10) -> None:
    _run("xdotool", "type", "--delay", str(gap_ms), "--", text)


def key(keysym: str) -> None:
    _run("xdotool", "key", "--clearmodifiers", keysym)


def chord(spec: str) -> None:
    _run("xdotool", "key", "--clearmodifiers", spec)


def activate(wid: int) -> None:
    _run("xdotool", "windowactivate", "--sync", str(wid))


def minimize(wid: int) -> None:
    _run("xdotool", "windowminimize", str(wid))


def maximize(wid: int) -> None:
    _run("xdotool", "windowactivate", str(wid))
    _run("wmctrl", "-i", "-r", str(wid), "-b", "add,maximized_vert,maximized_horz")


def close(wid: int) -> None:
    _run("xdotool", "windowclose", str(wid))
