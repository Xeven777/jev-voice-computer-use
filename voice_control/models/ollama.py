"""Ollama adapter: answer Jev-style {choice|noul} questions locally.

Sends one /api/chat request with format=json and a strict JSON schema so
small local models return parseable answers. Probability mass is normalised
per question; on parse failure it retries once with a repair nudge.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

import requests

DEFAULT_MODEL = os.environ.get("JEV_OLLAMA_MODEL", "qwen2.5:1.5b")
HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")


def _schema(questions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    props: dict[str, Any] = {}
    for name, q in questions.items():
        if q["type"] == "choice":
            props[name] = {
                "type": "object",
                "properties": {
                    "choice": {"type": "string"},
                    "probability": {"type": "number"},
                    "runner_up": {"type": "string"},
                    "runner_up_probability": {"type": "number"},
                },
                "required": ["choice", "probability"],
            }
        else:
            props[name] = {
                "type": "object",
                "properties": {"noul": {"type": "number"}},
                "required": ["noul"],
            }
    return {"type": "object", "properties": props, "required": list(questions)}


def _prompt(task: str, state: dict[str, Any], questions: dict[str, dict[str, Any]]) -> str:
    lines = [f"Task: {task}", "", f"State: {json.dumps(state)[:6000]}", ""]
    for name, q in questions.items():
        lines.append(f"Question '{name}' ({q['type']}): {q.get('instructions', '')}")
        if q["type"] == "choice":
            crit = q.get("criteria", {})
            if isinstance(crit, dict):
                for cid, desc in list(crit.items())[:255]:
                    lines.append(f"  - {cid}: {desc}")
            else:
                lines.append(f"  options: {crit}")
        lines.append(f"Reply with JSON object under key '{name}'.")
    lines.append("Return ONLY JSON matching the schema.")
    return "\n".join(lines)


def _normalise(name: str, q: dict[str, Any], ans: dict[str, Any]) -> dict[str, Any]:
    if q["type"] == "noul":
        try:
            ans["noul"] = max(0.0, min(1.0, float(ans.get("noul", 0.0))))
        except (TypeError, ValueError):
            ans["noul"] = 0.0
        return ans
    crit = q.get("criteria", {})
    choice = ans.get("choice")
    if choice not in crit:
        # sound-alike fallback: case-insensitive match, else 'none' if offered
        lowered = str(choice).casefold()
        for cid in crit:
            if str(cid).casefold() == lowered:
                choice = cid
                break
        else:
            choice = "none" if "none" in crit else next(iter(crit), "none")
        ans["choice"] = choice
    try:
        ans["probability"] = max(0.0, min(1.0, float(ans.get("probability", 0.5))))
    except (TypeError, ValueError):
        ans["probability"] = 0.5
    return ans


def ask_questions(key: str, task: str, state: dict[str, Any],
                  questions: dict[str, dict[str, Any]],
                  trace: list[dict[str, Any]] | None = None,
                  model: str = "") -> tuple[dict[str, dict[str, Any]], float]:
    model = model or DEFAULT_MODEL
    prompt = _prompt(task, state, questions)
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "format": _schema(questions),
        "stream": False,
        "options": {"temperature": 0.1},
    }
    call: dict[str, Any] = {"question": "+".join(questions), "request": payload,
                            "backend": "ollama", "model": model}
    if trace is not None:
        trace.append(call)
    start = time.perf_counter()
    try:
        resp = requests.post(f"{HOST}/api/chat", json=payload, timeout=120)
    except Exception as exc:
        call["error"] = str(exc)[:500]
        raise RuntimeError(f"Ollama is not reachable at {HOST}: {exc}") from exc
    elapsed = (time.perf_counter() - start) * 1000
    call["elapsed_ms"] = round(elapsed)
    call["http_status"] = resp.status_code
    resp.raise_for_status()
    result = resp.json()
    call["response"] = result
    raw = result.get("message", {}).get("content", "{}")
    try:
        answers = json.loads(raw)
    except json.JSONDecodeError:
        # repair pass: ask the model to re-emit JSON only
        fix = requests.post(f"{HOST}/api/chat", json={
            "model": model,
            "messages": [{"role": "user", "content": f"Re-emit ONLY valid JSON: {raw}"}],
            "format": _schema(questions), "stream": False,
            "options": {"temperature": 0.0}}, timeout=60)
        fix.raise_for_status()
        answers = json.loads(fix.json().get("message", {}).get("content", "{}"))
    out = {}
    for name, q in questions.items():
        ans = answers.get(name, {})
        if not isinstance(ans, dict):
            ans = {}
        out[name] = _normalise(name, q, ans)
    return out, elapsed
