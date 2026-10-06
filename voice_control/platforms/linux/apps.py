"""Installed-app catalog from .desktop files + launcher."""
from __future__ import annotations

import configparser
import os
import shutil
import subprocess
from pathlib import Path


def _desktop_dirs() -> list[Path]:
    dirs = [Path("/usr/share/applications"), Path("/usr/local/share/applications")]
    xdg = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
    dirs.append(Path(xdg) / "applications")
    dirs.append(Path.home() / ".local" / "share" / "applications")
    return [d for d in dirs if d.is_dir()]


def installed_apps() -> list[dict]:
    by_name: dict = {}
    for folder in _desktop_dirs():
        for path in sorted(folder.glob("*.desktop")):
            try:
                cp = configparser.ConfigParser(interpolation=None)
                with open(path, encoding="utf-8", errors="replace") as f:
                    cp.read_file(f)
                if "Desktop Entry" not in cp:
                    continue
                entry = cp["Desktop Entry"]
                if entry.get("NoDisplay", "false").lower() == "true":
                    continue
                if entry.get("Type", "Application") != "Application":
                    continue
                name = (entry.get("Name", "") or "").strip()
                if not name:
                    continue
                by_name.setdefault(name.casefold(), {"name": name, "path": str(path)})
            except Exception:
                continue
    return sorted(by_name.values(), key=lambda a: a["name"].casefold())


def _exec_argv(entry_path: str) -> list:
    """Exec= of a .desktop file as argv, with %f/%u-style field codes dropped."""
    try:
        cp = configparser.ConfigParser(interpolation=None)
        with open(entry_path, encoding="utf-8", errors="replace") as f:
            cp.read_file(f)
        execline = cp["Desktop Entry"].get("Exec", "").strip()
    except Exception:
        return []
    if not execline:
        return []
    import shlex
    return [t for t in shlex.split(execline) if not t.startswith("%")]


DEBUG = os.environ.get("JEV_DEBUG", "1") not in ("0", "", "false")


def launch(app: dict) -> str:
    name = app["name"]
    # Direct Exec= run first: reliable everywhere, no desktop-portal quirks.
    argv = _exec_argv(app["path"])
    if DEBUG:
        print(f"  launch {name}: exec={argv or '(none)'}", flush=True)
    if argv and shutil.which(argv[0]):
        try:
            if DEBUG:
                print(f"  $ {' '.join(argv)}", flush=True)
            subprocess.Popen(argv, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
            return f'launched "{name}"'
        except OSError:
            pass
    for tool, args in (("gio", ["open"]), ("xdg-open", [])):
        if shutil.which(tool) is None:
            continue
        try:
            if DEBUG:
                print(f"  $ {tool} {' '.join(args)} {app['path']}", flush=True)
            subprocess.Popen([tool, *args, app["path"]],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
            return f'launched "{name}"'
        except OSError:
            continue
    raise RuntimeError(f"Could not launch {name}: no launcher found")
