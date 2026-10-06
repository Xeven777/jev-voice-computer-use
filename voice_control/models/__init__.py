"""Model adapters: Jev (OpenRouter/TypeSafe) vs local Ollama.

Both expose ask_questions(key, task, state, questions, trace) so core.py /
goal.py stay unchanged. Select with JEV_MODEL=jev|ollama.
"""
from __future__ import annotations

import os
