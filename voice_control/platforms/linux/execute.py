"""Linux executor: mirrors windows.execute() over xdotool."""
from __future__ import annotations

import time
from typing import Any

from ...core import (CHORDS, FIELD_ROLES, PRESS_KEYS, SURFACE_ID,
                     Control, dictation_text)
from . import apps, input as inp, screen

TYPE_GAP_MS = 10

PRESS_MAP = {
    "Enter": "Return", "Escape": "Escape", "Tab": "Tab", "Shift+Tab": "Shift+Tab",
    "Backspace": "BackSpace", "Delete": "Delete", "Home": "Home", "End": "End",
    "PageUp": "Page_Up", "PageDown": "Page_Down", "Space": "space",
}

CHORD_MAP = {
    "back": "Alt+Left", "forward": "Alt+Right", "refresh": "ctrl+r",
    "find": "ctrl+f", "next_tab": "ctrl+Tab", "previous_tab": "ctrl+Shift+Tab",
    "new_tab": "ctrl+t", "close_tab": "ctrl+w", "copy": "ctrl+c",
    "paste": "ctrl+v", "select_all": "ctrl+a", "save": "ctrl+s",
    "undo": "ctrl+z", "redo": "ctrl+Shift+z", "full_screen": "F11",
}


def _center(rect: tuple) -> tuple:
    l, t, r, b = rect
    return ((l + r) // 2, (t + b) // 2)


def _wait_foreground(wid: int, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if screen.active_window_id() == wid:
            return
        time.sleep(0.1)

def execute(verb: str, target: dict, state: dict,
            controls: list, app_list: list,
            utterance: str, app_hwnd: Any = None,
            text: str | None = None) -> str:
    wid = state["activeWindow"]["wid"]
    if verb not in {"switch_window", "launch_app", "alt_tab"}:
        _wait_foreground(wid)
    if verb in {"left_click", "right_click", "double_click"} \
            and target.get("id") == SURFACE_ID:
        rect = screen.window_rect(wid)
        x, y = _center(rect)
        if verb == "left_click":
            inp.click(x, y)
        elif verb == "right_click":
            inp.right_click(x, y)
        else:
            inp.double_click(x, y)
        return f"{verb} content area"
    if verb in {"left_click", "right_click", "double_click", "hover",
                "type_text", "select_text", "set_slider"}:
        chosen = next((c for c in controls if c.id == target["id"]), None)
        if chosen is None:
            raise RuntimeError("Selected target is not in captured controls")
        x, y = _center(chosen.rect)
        if verb == "hover":
            inp.hover(x, y)
            return f'hovered {chosen.role} "{chosen.name}"'
        if verb in {"left_click", "right_click", "double_click"}:
            if verb == "left_click":
                inp.click(x, y)
            elif verb == "right_click":
                inp.right_click(x, y)
            else:
                inp.double_click(x, y)
            return f'{verb} {chosen.role} "{chosen.name}"'
        if verb == "type_text":
            text = text or dictation_text(utterance)
            if not text or chosen.role not in FIELD_ROLES:
                raise RuntimeError("Say 'type <text>' while an editable field is available")
            inp.click(x, y)
            inp.chord("ctrl+a")
            inp.type_text(text, gap_ms=TYPE_GAP_MS)
            where = chosen.name or "edit field"
            return f"typed {len(text)} characters into {where}"
        if verb == "select_text":
            if not text or chosen.role not in FIELD_ROLES:
                raise RuntimeError("Nothing to select")
            inp.click(x, y)
            inp.chord("ctrl+a")
            inp.type_text(text, gap_ms=TYPE_GAP_MS)
            return f'selected "{text}" in {chosen.name or "the field"}'
        raise RuntimeError("set_slider needs arrow keys on Linux")
    if verb in {"scroll_up", "scroll_down", "scroll_left", "scroll_right"}:
        x, y = _center(screen.window_rect(wid))
        inp.hover(x, y)
        {"scroll_up": inp.scroll_up, "scroll_down": inp.scroll_down,
         "scroll_left": inp.scroll_left, "scroll_right": inp.scroll_right}[verb]()
        return f"{verb} 3 wheel notches"
    if verb in {"zoom_in", "zoom_out", "zoom_reset"}:
        inp.chord({"zoom_in": "ctrl+plus", "zoom_out": "ctrl+minus",
                   "zoom_reset": "ctrl+0"}[verb])
        return f"{verb} via Ctrl shortcut (app-dependent)"
    if verb == "press_key":
        keysym = PRESS_MAP.get(str(target.get("key", "")))
        if not keysym or target.get("key") not in PRESS_KEYS:
            raise RuntimeError("Key is outside the allowed catalog")
        inp.key(keysym)
        return f"pressed {target['key']}"
    if verb == "key_chord":
        name = target.get("key")
        if name not in CHORDS or name not in CHORD_MAP:
            raise RuntimeError("Shortcut is outside the allowed catalog")
        inp.chord(CHORD_MAP[name])
        return f"sent {CHORDS[name][0]} ({name})"
    if verb in {"minimize_window", "maximize_window", "close_window"}:
        if target["id"] != "current":
            wid = int(target["id"][1:])
            if wid not in {w["wid"] for w in screen.open_windows()}:
                raise RuntimeError("Target window is no longer open")
        if verb == "close_window":
            inp.close(wid)
            return "requested window close"
        if verb == "minimize_window":
            inp.minimize(wid)
            return "minimized window"
        inp.maximize(wid)
        return "maximized window"
    if verb == "switch_window":
        dest = int(target["id"][1:])
        if dest not in {w["wid"] for w in screen.open_windows()}:
            raise RuntimeError("Target window is no longer open")
        inp.activate(dest)
        _wait_foreground(dest)
        return f"activated window {dest}"
    if verb == "wait":
        time.sleep(1.0)
        return "waited 1 s for the app to respond"
    if verb == "alt_tab":
        inp.chord("Alt+Tab")
        return "sent Alt+Tab (destination not guaranteed)"
    if verb == "launch_app":
        index = int(target["id"][1:])
        if not 0 <= index < len(app_list):
            raise RuntimeError("Installed app choice is invalid")
        return apps.launch(app_list[index])
    raise RuntimeError(f"No executor for {verb}")
