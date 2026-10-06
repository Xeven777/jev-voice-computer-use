"""AT-SPI screen capture -> core.Control list. X11 + XFCE first."""
from __future__ import annotations

from typing import Any

from ...core import Control, SURFACE_ID
from ...uia_watch import LOADING_NAME
from . import screen

MAX_DEPTH = 45
MAX_TEXTS = 60
MAX_DETAIL = 100
TEXT_ROLES = {"Text", "Header", "StatusBar", "TitleBar", "Label", "Static"}

ROLE_MAP = {
    "push button": "Button", "button": "Button", "toggle button": "Button",
    "link": "Hyperlink", "menu item": "MenuItem", "list item": "ListItem",
    "tree item": "TreeItem", "page tab": "TabItem", "entry": "Edit",
    "password text": "Edit", "text": "Edit", "check box": "CheckBox",
    "radio button": "RadioButton", "combo box": "ComboBox",
    "spin button": "Spinner", "slider": "Slider", "document text": "Document",
    "document frame": "Document", "heading": "Header",
}


def _atspi():
    try:
        import gi
        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi
        Atspi.init()
        return Atspi
    except Exception:
        return None


def _role_name(Atspi, obj) -> str:
    try:
        return Atspi.Accessible.get_role_name(obj).lower()
    except Exception:
        return ""


def _name(obj) -> str:
    try:
        return (obj.get_name() or "").strip()
    except Exception:
        return ""


def _rect(obj, Atspi) -> tuple:
    try:
        comp = obj.get_component_iface()
        if comp is None:
            return (0, 0, 0, 0)
        r = comp.get_extents(Atspi.CoordType.SCREEN)
        return (r.x, r.y, r.x + r.width, r.y + r.height)
    except Exception:
        return (0, 0, 0, 0)


def _visible(obj, Atspi) -> bool:
    try:
        return bool(obj.get_state_set().contains_state(Atspi.StateType.SHOWING))
    except Exception:
        return True


def _state_str(obj, Atspi) -> str:
    try:
        st = obj.get_state_set()
    except Exception:
        return ""
    out: list = []
    for attr, label in (("CHECKED", "checked"), ("SELECTED", "selected"),
                        ("EXPANDED", "expanded"), ("FOCUSED", "focused"),
                        ("HAS_POPUP", "has submenu")):
        try:
            if st.contains_state(getattr(Atspi.StateType, attr)):
                out.append(label)
        except Exception:
            pass
    return ", ".join(out)


def _outside(bounds: tuple, area: tuple) -> bool:
    l, t, r, b = bounds
    if r <= l or b <= t:
        return False
    return r <= area[0] or l >= area[2] or b <= area[1] or t >= area[3]


def _field_value(child) -> str:
    try:
        editable = child.get_editable_text_iface()
        if editable is not None:
            return (editable.get_text(0, -1) or "").strip()[:200]
    except Exception:
        pass
    try:
        text = child.get_text_iface()
        if text is not None:
            return (text.get_text(0, -1) or "").strip()[:200]
    except Exception:
        pass
    return ""
def _walk(Atspi, obj, depth, area, controls, texts, loading,
          parent_path, visited, max_nodes) -> bool:
    if visited[0] >= max_nodes:
        return True
    visited[0] += 1
    try:
        n_children = obj.get_child_count()
    except Exception:
        return False
    for i in range(n_children):
        if visited[0] >= max_nodes:
            return True
        try:
            child = obj.get_child_at_index(i)
        except Exception:
            continue
        role = ROLE_MAP.get(_role_name(Atspi, child), "")
        name = _name(child)
        bounds = _rect(child, Atspi)
        visible = _visible(child, Atspi)
        if depth and _outside(bounds, area):
            continue
        path = (parent_path + " > " + name).strip(" >")[-180:] if name else parent_path
        if visible and role in TEXT_ROLES and name and len(texts) < MAX_TEXTS \
                and len(name) <= 120 and name not in texts:
            texts.append(name)
        if visible and name and len(name) <= 80:
            try:
                if LOADING_NAME.search(name):
                    loading.append(f'"{name}"')
            except Exception:
                pass
        child_path = path
        if visible and role and (name or role in {"Edit", "ComboBox", "Spinner", "Slider", "Document"}):
            state = _state_str(child, Atspi)
            value = ""
            if role in {"Edit", "ComboBox", "Spinner", "Document"}:
                value = _field_value(child)
                if value == name:
                    value = ""
            enabled = True
            try:
                st = child.get_state_set()
                if hasattr(Atspi.StateType, "ENABLED"):
                    enabled = bool(st.contains_state(Atspi.StateType.ENABLED))
                elif hasattr(Atspi.StateType, "SENSITIVE"):
                    enabled = bool(st.contains_state(Atspi.StateType.SENSITIVE))
            except Exception:
                pass
            controls.append(Control(f"c{len(controls):04d}", name, role, bounds,
                                    parent_path[-120:], enabled, 0, state,
                                    detail="", value=value))
        if depth + 1 < MAX_DEPTH:
            if _walk(Atspi, child, depth + 1, area, controls, texts, loading,
                     child_path, visited, max_nodes):
                return True
    return False


def capture(wid=None, max_nodes=3000):
    wid = wid or screen.active_window_id()
    if not wid:
        raise RuntimeError("No foreground window is available")
    windows = screen.open_windows()
    title = screen.window_name(wid)
    pid = screen.window_pid(wid)
    active = next((w for w in windows if w["wid"] == wid), None)
    if not active:
        active = {"wid": wid, "title": title, "process": screen.process_name(pid)}
    area = screen.window_rect(wid)
    controls: list = []
    texts: list = []
    loading: list = []
    truncated = False
    Atspi = _atspi()
    if Atspi is not None:
        try:
            desktop = Atspi.get_desktop(0)
            match = None
            for i in range(desktop.get_child_count()):
                try:
                    app = desktop.get_child_at_index(i)
                except Exception:
                    continue
                try:
                    for j in range(app.get_child_count()):
                        w = app.get_child_at_index(j)
                        wname = _name(w)
                        if wname and (wname == title or title in wname or wname in title):
                            match = w
                            break
                except Exception:
                    continue
                if match is not None:
                    break
            root = match if match is not None else desktop
            visited = [0]
            truncated = _walk(Atspi, root, 0, area, controls, texts, loading,
                              str(active.get("process", "")), visited, max_nodes)
        except Exception:
            controls, truncated = [], False
    if not controls:
        l, t, r, b = area
        if r > l and b > t:
            controls.append(Control(SURFACE_ID, active.get("process", "") or title or "window",
                                    "Document", area, "", True, 0, "content area"))
    state = {
        "activeWindow": active, "openWindows": windows, "openMenus": 0,
        "texts": texts, "loading": loading, "covered": [],
        "controlCount": len(controls), "truncatedTraversal": truncated,
        "controls": [{"id": c.id, "role": c.role, "name": c.name, "rect": c.rect,
                      "path": c.path, "enabled": c.enabled,
                      **({"state": c.state} if c.state else {}),
                      **({"detail": c.detail} if c.detail else {}),
                      **({"value": c.value} if c.value else {})} for c in controls],
    }
    return state, controls


