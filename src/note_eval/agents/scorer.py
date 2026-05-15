from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from pydantic import BaseModel

from ..llm import MAX_CONCURRENT_LLM_CALLS, LLMClient
from ..prompts import SCORER
from ..schemas.note import Note
from ..schemas.rubric import Rubric, RubricItem
from ..schemas.score import Score, ScoreValue
from ..storage.cache import Cache

log = logging.getLogger(__name__)

BATCH_MODE = False  # If True, score all applicable rubric items in one call (not implemented).

_SYSTEM = "You are an evaluator scoring notes against a rubric. Always return structured JSON."


class _ScorerLLMResponse(BaseModel):
    score: ScoreValue
    evidence_span: str
    rationale: str
    confidence: Literal["high", "low"]


def _format_user_prompt(note: Note, item: RubricItem) -> str:
    return SCORER.format(
        rubric_item_name=item.name,
        rubric_item_description=item.description,
        anchor_0=item.anchors.score_0,
        anchor_1=item.anchors.score_1,
        anchor_2=item.anchors.score_2,
        note_text=note.text,
    )


def score_note_item(
    note: Note,
    item: RubricItem,
    rubric_version: str,
    llm: LLMClient,
    cache: Cache,
) -> Score:
    key = Cache.make_key(note.note_id, item.id, rubric_version)
    hit = cache.get(key)
    if hit is not None:
        return hit

    user = _format_user_prompt(note, item)
    response = llm.complete(_SYSTEM, user, _ScorerLLMResponse)
    assert isinstance(response, _ScorerLLMResponse)

    score = Score(
        note_id=note.note_id,
        author_id=note.author_id,
        event_type=note.event_type,
        occurred_at=note.occurred_at.isoformat(),
        rubric_item_id=item.id,
        rubric_version=rubric_version,
        score=response.score,
        evidence_span=response.evidence_span if response.score != "insufficient_evidence" else "",
        rationale=response.rationale,
        confidence=response.confidence,
    )
    cache.set(key, score)
    return score


def score_notes(
    notes: list[Note],
    rubric: Rubric,
    llm: LLMClient,
    cache: Cache,
) -> list[Score]:
    tasks: list[tuple[Note, RubricItem]] = []
    for note in notes:
        if not note.text.strip():
            log.warning("Skipping empty note %s", note.note_id)
            continue
        for item in rubric.items_for_event_type(note.event_type):
            tasks.append((note, item))

    if not tasks:
        return []

    if BATCH_MODE:
        raise NotImplementedError("BATCH_MODE is not implemented")

    results: list[Score] = []
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_LLM_CALLS) as pool:
        for score in pool.map(
            lambda pair: score_note_item(pair[0], pair[1], rubric.version, llm, cache),
            tasks,
        ):
            results.append(score)
    return results
