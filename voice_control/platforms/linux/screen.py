"""Linux screen helpers: X11 active window, open windows, settle (X11/XFCE first)."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from typing import Any

import psutil

DEBUG = os.environ.get("JEV_DEBUG", "1") not in ("0", "", "false")


def _run(*args: str, timeout: float = 5.0) -> str:
    if DEBUG:
        print(f"  $ {' '.join(args)}", flush=True)
    out = subprocess.run(list(args), capture_output=True, text=True, timeout=timeout)
    if out.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed: {out.stderr.strip()[:200]}")
    return out.stdout


def active_window_id() -> int:
    try:
        return int(_run("xdotool", "getactivewindow").strip())
    except Exception:
        return 0


def active_hwnd_compat() -> int:
    """Alias so core._window_targets(hwnd) comparisons keep working."""
    return active_window_id()


def window_name(wid: int) -> str:
    try:
        return _run("xdotool", "getwindowname", str(wid)).strip()
    except Exception:
        return ""


def window_rect(wid: int) -> tuple[int, int, int, int]:
    """(left, top, right, bottom) via xdotool getwindowgeometry."""
    try:
        text = _run("xdotool", "getwindowgeometry", "--shell", str(wid))
        vals: dict[str, int] = {}
        for line in text.splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                vals[k.strip()] = int(v.strip())
        x, y = vals.get("X", 0), vals.get("Y", 0)
        w, h = vals.get("WIDTH", 0), vals.get("HEIGHT", 0)
        return (x, y, x + w, y + h)
    except Exception:
        return (0, 0, 0, 0)


def window_pid(wid: int) -> int:
    try:
        return int(_run("xdotool", "getwindowpid", str(wid)).strip())
    except Exception:
        return 0


def process_name(pid: int) -> str:
    try:
        return psutil.Process(pid).name()
    except Exception:
        return str(pid) if pid else ""


def open_windows() -> list[dict[str, Any]]:
    """Visible windows via wmctrl (fallback: just the active window)."""
    if shutil.which("wmctrl") is None:
        wid = active_window_id()
        if not wid:
            return []
        return [{"wid": wid, "title": window_name(wid), "process": process_name(window_pid(wid))}]
    try:
        text = _run("wmctrl", "-l", "-p")
    except Exception:
        return []
    windows: list[dict[str, Any]] = []
    for line in text.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        try:
            wid = int(parts[0], 16)
        except ValueError:
            continue
        try:
            pid = int(parts[2])
        except ValueError:
            pid = 0
        # wmctrl -l: "<wid> <desktop> <pid> <host> <title>"; desktop -1 = panel/desktop, skip.
        try:
            desktop = int(parts[1])
        except ValueError:
            desktop = 0
        if desktop == -1:
            continue
        rest = parts[3]
        title = rest.split(None, 1)[1].strip() if " " in rest.strip() else ""
        if not title or title in ("Desktop",):
            continue
        entry = {"wid": wid, "hwnd": wid, "title": title, "process": process_name(pid)}
        windows.append(entry)
    return windows


def top_level_picture() -> tuple:
    shown: list[tuple] = []
    for w in open_windows():
        wid = w["wid"]
        shown.append((wid, w["title"], window_rect(wid)))
    wid = active_window_id()
    return wid, window_name(wid), tuple(shown)


def settle(verb: str, before: tuple, timeout_s: float = 3.0) -> int:
    started = time.monotonic()
    if verb in {"launch_app", "switch_window", "alt_tab"}:
        while time.monotonic() - started < 10 and top_level_picture()[:2] == before[:2]:
            time.sleep(0.1)
    time.sleep(0.3)
    previous = top_level_picture()
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        time.sleep(0.15)
        current = top_level_picture()
        if current == previous:
            break
        previous = current
    return round((time.monotonic() - started) * 1000)
