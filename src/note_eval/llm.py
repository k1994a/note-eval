from __future__ import annotations

import hashlib
import os
import random
import re
import threading
import time
import typing
from typing import Any, Literal, Protocol, Union, get_args, get_origin

from pydantic import BaseModel

MAX_CONCURRENT_LLM_CALLS = 10


class LLMClient(Protocol):
    def complete(self, system: str, user: str, response_model: type[BaseModel]) -> BaseModel: ...


def _seed_from(system: str, user: str) -> int:
    return int(hashlib.sha256((system + user).encode("utf-8")).hexdigest(), 16)


def _first_sentence(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    match = re.search(r"(.+?[.!?])(\s|$)", text, flags=re.DOTALL)
    return (match.group(1) if match else text)[:200].strip()


def _keywords(text: str, n: int = 5) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text or "")
    seen: list[str] = []
    for w in words:
        lw = w.lower()
        if lw in seen:
            continue
        seen.append(lw)
        if len(seen) >= n:
            break
    return seen


def _is_scorer_response(model: type[BaseModel]) -> bool:
    expected = {"score", "evidence_span", "rationale", "confidence"}
    return expected.issubset(set(model.model_fields.keys()))


def _build_value(annotation: Any, seed: int, user: str, field_name: str) -> Any:
    rng = random.Random(seed ^ hash(field_name))

    if annotation is type(None):
        return None

    origin = get_origin(annotation)

    if origin is Union or origin is typing.Union:
        args = [a for a in get_args(annotation) if a is not type(None)]
        if not args:
            return None
        if type(None) in get_args(annotation) and seed % 7 == 0 and field_name == "mean_score":
            return None
        return _build_value(args[0], seed, user, field_name)

    if origin is Literal:
        choices = list(get_args(annotation))
        return choices[seed % len(choices)]

    if origin in (list, list):
        (inner,) = get_args(annotation) or (str,)
        # 2 elements by default — matches RecentSummary requirement; harmless elsewhere
        return [
            _build_value(inner, seed + i + 1, user, f"{field_name}_{i}")
            for i in range(2)
        ]

    if origin in (dict, dict):
        key_t, val_t = get_args(annotation) or (str, str)
        kws = _keywords(user, 2) or ["item_a", "item_b"]
        return {
            str(k): _build_value(val_t, seed + i + 1, user, f"{field_name}_{k}")
            for i, k in enumerate(kws)
        }

    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return _build_model_instance(annotation, seed, user)

    if annotation is str:
        return _mock_string(field_name, user, rng)
    if annotation is int:
        return rng.randint(0, 5)
    if annotation is float:
        return round(rng.uniform(0.0, 2.0), 2)
    if annotation is bool:
        return bool(rng.randint(0, 1))

    return None


def _mock_string(field_name: str, user: str, rng: random.Random) -> str:
    fn = field_name.lower()
    kws = _keywords(user, 4) or ["topic", "context", "observation"]
    kws_str = ", ".join(kws)

    if "evidence" in fn and "rate" not in fn:
        sentence = _first_sentence(user)
        return sentence or ""
    if "rationale" in fn:
        return f"Mock rationale referencing {kws[0]}."
    if "summary" in fn or "narrative" in fn or "themes" in fn:
        return f"Mock summary noting patterns around {kws_str}."
    if "improving" in fn or "declining" in fn or "persistently_weak" in fn or "bullet" in fn:
        return f"Mock bullet about {kws[0]}."
    if "id" in fn:
        return f"mock_{rng.randint(1000, 9999)}"
    if "month" in fn:
        return "2026-01"
    if "window" in fn or "at" in fn:
        return "2026-01-01T00:00:00+00:00"
    if "version" in fn:
        return "mock-1"
    if "event_type" in fn or "author" in fn or "subject" in fn:
        return f"mock_{rng.randint(1, 99)}"
    if "name" in fn:
        return f"Mock {kws[0]}"
    if "description" in fn:
        return f"Mock description about {kws_str}."
    return f"Mock {fn} ({kws[0]})"


def _build_model_instance(model: type[BaseModel], seed: int, user: str) -> BaseModel:
    if _is_scorer_response(model):
        return _build_scorer_response(model, seed, user)

    values: dict[str, Any] = {}
    hints = typing.get_type_hints(model)
    for fname, finfo in model.model_fields.items():
        ann = hints.get(fname, finfo.annotation)
        values[fname] = _build_value(ann, seed, user, fname)
    return model(**values)


def _build_scorer_response(model: type[BaseModel], seed: int, user: str) -> BaseModel:
    insufficient = (seed % 100) < 15
    if insufficient:
        score: Any = "insufficient_evidence"
        evidence = ""
        rationale = "Mock rationale: insufficient evidence in the note text."
    else:
        score = seed % 3  # 0, 1, or 2
        evidence = _first_sentence(user)
        rationale = "Mock rationale based on note content."
    confidence = "low" if seed % 5 == 0 else "high"

    values: dict[str, Any] = {
        "score": score,
        "evidence_span": evidence,
        "rationale": rationale,
        "confidence": confidence,
    }

    # Some scorer-response models may include other deterministic fields too.
    hints = typing.get_type_hints(model)
    for fname, finfo in model.model_fields.items():
        if fname in values:
            continue
        ann = hints.get(fname, finfo.annotation)
        values[fname] = _build_value(ann, seed, user, fname)
    return model(**values)


class MockLLMClient:
    """Deterministic mock keyed off the hash of (system + user)."""

    def complete(self, system: str, user: str, response_model: type[BaseModel]) -> BaseModel:
        seed = _seed_from(system, user)
        return _build_model_instance(response_model, seed, user)


class LiveOpenAIClient:
    """Wraps openai.OpenAI with structured outputs via response_format=BaseModel.

    Retries with exponential backoff on rate-limit / 5xx errors. Respects
    MAX_CONCURRENT_LLM_CALLS via a class-level semaphore so callers may run
    in a thread pool without overloading the API.
    """

    _semaphore = threading.Semaphore(MAX_CONCURRENT_LLM_CALLS)

    def __init__(self, model: str = "gpt-4o-mini", max_retries: int = 5):
        from openai import OpenAI

        self._client = OpenAI()
        self._model = model
        self._max_retries = max_retries

    def complete(self, system: str, user: str, response_model: type[BaseModel]) -> BaseModel:
        from openai import APIStatusError, InternalServerError, RateLimitError

        delay = 1.0
        last_exc: Exception | None = None
        with self._semaphore:
            for _attempt in range(self._max_retries):
                try:
                    completion = self._client.beta.chat.completions.parse(
                        model=self._model,
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        response_format=response_model,
                    )
                    parsed = completion.choices[0].message.parsed
                    if parsed is None:
                        raise RuntimeError("OpenAI returned no parsed response")
                    return parsed
                except (RateLimitError, InternalServerError) as exc:
                    last_exc = exc
                except APIStatusError as exc:
                    if 500 <= getattr(exc, "status_code", 0) < 600:
                        last_exc = exc
                    else:
                        raise
                time.sleep(delay)
                delay *= 2
        assert last_exc is not None
        raise last_exc


def get_client() -> LLMClient:
    mode = os.getenv("NOTE_EVAL_LLM_MODE", "mock")
    if mode == "live":
        return LiveOpenAIClient()
    return MockLLMClient()
