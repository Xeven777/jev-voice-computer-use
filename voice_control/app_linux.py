"""Headless Linux entry: text command -> observe -> model decides -> execute.

Usage:
    JEV_MODEL=ollaya JEV_PLATFORM=linux python3 -m voice_control.app_linux "open firefox"
    JEV_MODEL=ollaya python3 -m voice_control.app_linux --goal "open the file manager"
    JEV_MODEL=ollaya python3 -m voice_control.app_linux --repl   # interactive
Push-to-talk tray comes later; this validates the whole loop first.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    ap = argparse.ArgumentParser(description="Jev Voice (Linux): text-driven agent loop")
    ap.add_argument("command", nargs="?", default="", help="Single command, e.g. 'open firefox'")
    ap.add_argument("--goal", default="", help="Multi-step goal via goal.run_goal")
    ap.add_argument("--repl", action="store_true")
    ap.add_argument("--model", default=os.environ.get("JEV_OLLAMA_MODEL", "qwen2.5:1.5b"))
    ap.add_argument("--dry-run", action="store_true", help="Print the plan, do not execute")
    args = ap.parse_args()

    from voice_control import core, goal
    from voice_control.models import router
    from voice_control.platform_api import load_backend

    backend = load_backend("linux")
    os.environ["JEV_OLLAMA_MODEL"] = args.model
    # Route core and goal Jev calls through the local backend when asked.
    router.install()

    def run_once(task: str, use_goal: bool) -> dict:
        record: dict = {"utterance_id": f"linux-{int(time.time()*1000)}",
                        "task": task, "jev_calls": []}
        if use_goal:
            def observe(_hwnd=None):
                return backend.capture_settled()
            apps = backend.installed_apps()

            def act_fn(verb, target, state, controls, text=None):
                return backend.execute(verb, target, state, controls, apps,
                                       task, None, text)
            outcome = goal.run_goal("", task, observe, act_fn, record)
            record["outcome"] = outcome
            return record
        state, controls = backend.capture_settled()
        apps = backend.installed_apps()
        core.plan_command("", task, state, controls, apps, record)
        if args.dry_run:
            record["dry_run"] = True
            return record
        msg = backend.execute(record["verb"]["choice"], record.get("target", {}),
                              state, controls, apps, task, None, record.get("text"))
        record["result"] = msg
        return record

    tasks: list[tuple[str, bool]] = []
    if args.repl:
        print(f"jev-linux repl (model={args.model}). 'goal: ...' for multi-step, empty quits.")
        while True:
            try:
                line = input("> ").strip()
            except EOFError:
                break
            if not line:
                break
            use_goal = line.startswith("goal:")
            tasks.append((line[5:].strip() if use_goal else line, use_goal))
    elif args.goal:
        tasks.append((args.goal, True))
    elif args.command:
        tasks.append((args.command, False))
    else:
        ap.print_help()
        return 2
    code = 0
    for task, use_goal in tasks:
        try:
            rec = run_once(task, use_goal)
            print(json.dumps(rec, indent=1, default=str)[:4000])
        except Exception as exc:
            code = 1
            print(f"ERROR: {exc}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
