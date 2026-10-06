"""Ollaya adapter: local decision models (e.g. laya) behind a Jev-compatible API.

Ollaya serves a TypeSafe-compatible decisions API locally (default
http://localhost:11435), so this sends the same {model, state, questions}
body as core.ask_questions and returns the same {choice, probabilities,
confidence} / {noul} answers. No API key needed; any Bearer value is accepted.

Install: curl -fsSL https://ollaya.dev/install.sh | sh && ollaya pull laya
Run:     JEV_MODEL=ollaya python3 -m voice_control.app_linux "open firefox"
"""
from __future__ import annotations

import os
import time
from typing import Any

import requests

HOST = os.environ.get("OLLAYA_HOST", "http://localhost:11435")
# multilingual has double the context (1024 vs 512): busy screens overflow
# laya:en's 512 tokens and the server refuses (STATE_TRUNCATED).
DEFAULT_MODEL = os.environ.get("OLLAYA_MODEL", "laya:multilingual")


def ask_questions(key: str, task: str, state: dict[str, Any],
                   questions: dict[str, dict[str, Any]],
                   trace: list[dict[str, Any]] | None = None,
                   model: str = "") -> tuple[dict[str, dict[str, Any]], float]:
    model = model or DEFAULT_MODEL
    # Ollaya rejects choice questions with fewer than 2 options (hosted Jev
    # accepts them): answer those deterministically. A lone "none" target
    # then flows into the usual no-confident-target refusal downstream.
    answers: dict[str, dict[str, Any]] = {}
    live: dict[str, dict[str, Any]] = {}
    for name, q in questions.items():
        criteria = q.get("criteria") or {}
        if q["type"] == "choice" and len(criteria) < 2:
            sole = next(iter(criteria), "none")
            answers[name] = {"type": "choice", "choice": sole, "confidence": 1.0,
                             "probabilities": {sole: 1.0}}
        else:
            live[name] = q
    if not live:
        if trace is not None:
            trace.append({"question": "+".join(questions), "request": None, "backend": "ollaya",
                          "model": model, "synthesized": True, "elapsed_ms": 0,
                          "response": {"answers": answers}})
        return answers, 0.0
    payload = {"model": model, "state": {"task": task, **state}, "questions": live}
    call: dict[str, Any] = {"question": "+".join(live), "request": payload,
                            "backend": "ollaya", "model": model}
    if trace is not None:
        trace.append(call)
    start = time.perf_counter()
    try:
        # /api/decide is the native endpoint: same answers shape as the
        # TypeSafe-compatible /v1/* paths, but it truncates overlong states
        # instead of refusing them (HTTP 422 STATE_TRUNCATED on busy screens).
        resp = requests.post(f"{HOST}/api/decide",
                             headers={"Authorization": f"Bearer {key or 'ollaya-local'}",
                                      "Content-Type": "application/json"},
                             json=payload, timeout=120)
    except Exception as exc:
        call["error"] = str(exc)[:500]
        raise RuntimeError(f"Ollaya is not reachable at {HOST}: {exc}") from exc
    elapsed = (time.perf_counter() - start) * 1000
    call["elapsed_ms"] = round(elapsed)
    call["http_status"] = resp.status_code
    if resp.status_code >= 400:
        body = str(getattr(resp, "text", ""))[:2000]
        call["error_body"] = body
        raise RuntimeError(f"Ollaya rejected the { '+'.join(live)} request "
                           f"(HTTP {resp.status_code}): {body}")
    result = resp.json()
    call["response"] = result
    live_answers = result.get("answers", {})
    for name, question in live.items():
        answer = live_answers.get(name, {})
        if question["type"] == "choice" and answer.get("choice") not in question.get("criteria", {}):
            raise RuntimeError(f"Ollaya returned an invalid {name}: {answer.get('choice')!r}")
        if question["type"] == "noul" and not isinstance(answer.get("noul"), (int, float)):
            raise RuntimeError(f"Ollaya returned no probability for {name}")
    answers.update(live_answers)
    return answers, elapsed
