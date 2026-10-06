"""Model router: JEV_MODEL=jev (default), ollama, or ollaya."""
from __future__ import annotations

import os
from typing import Any


def backend_name() -> str:
    val = os.environ.get("JEV_MODEL", "jev").strip().lower()
    return val if val in ("ollama", "ollaya") else "jev"


def ask_questions(key: str, task: str, state: dict[str, Any],
                  questions: dict[str, dict[str, Any]],
                  trace: list[dict[str, Any]] | None = None):
    if backend_name() == "ollama":
        from .ollama import ask_questions as ask_ollama
        return ask_ollama(key, task, state, questions, trace)
    if backend_name() == "ollaya":
        from .ollaya import ask_questions as ask_ollaya
        return ask_ollaya(key, task, state, questions, trace)
    from ..core import ask_questions as ask_jev
    return ask_jev(key, task, state, questions, trace)


def install() -> str:
    """Route every Jev call through the selected backend, including goal.py
    (which imported ask_questions directly, so patching core alone misses it)."""
    from .. import core, goal
    name = backend_name()
    if name != "jev":
        core.ask_questions = ask_questions  # type: ignore
        goal.ask_questions = ask_questions  # type: ignore
    return name
