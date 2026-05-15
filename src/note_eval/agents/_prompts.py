from __future__ import annotations

from functools import cache
from importlib import resources


@cache
def load_prompt(name: str) -> str:
    return resources.files("note_eval.prompts").joinpath(name).read_text(encoding="utf-8")
