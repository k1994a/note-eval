from __future__ import annotations

import json

from pydantic import BaseModel

from .. import aggregation
from ..llm import LLMClient
from ..schemas.note import Note
from ..schemas.rubric import Rubric
from ..schemas.score import Score
from ..schemas.summary import MonthlySummary, RubricItemSummary
from ._prompts import load_prompt

_SYSTEM = "You are summarizing one author's monthly performance. Return structured JSON."


class _MonthlyItemNarrative(BaseModel):
    rubric_item_id: str
    qualitative_summary: str
    representative_evidence: list[str]


class _MonthlyLLMResponse(BaseModel):
    per_item: list[_MonthlyItemNarrative]
    cross_item_themes: str


def _format_score_table(rows: dict[str, dict]) -> str:
    return json.dumps(rows, indent=2)


def _format_evidence(evidence_by_item: dict[str, list[str]]) -> str:
    out_lines: list[str] = []
    for item_id, spans in evidence_by_item.items():
        out_lines.append(f"- {item_id}:")
        for span in spans[:8]:  # cap to avoid prompt bloat
            cleaned = span.replace("\n", " ").strip()
            if cleaned:
                out_lines.append(f"    * {cleaned!r}")
    return "\n".join(out_lines) or "(no evidence)"


def summarize_month(
    author_id: str,
    event_type: str,
    month: str,
    scores: list[Score],
    notes_by_id: dict[str, Note],
    rubric: Rubric,
    llm: LLMClient,
) -> MonthlySummary:
    applicable_items = rubric.items_for_event_type(event_type)

    scores_by_item: dict[str, list[Score]] = {}
    for item in applicable_items:
        scores_by_item[item.id] = [s for s in scores if s.rubric_item_id == item.id]

    rows_for_prompt: dict[str, dict] = {}
    evidence_by_item: dict[str, list[str]] = {}
    for item in applicable_items:
        item_scores = scores_by_item[item.id]
        rows_for_prompt[item.id] = {
            "name": item.name,
            "distribution": aggregation.score_distribution(item_scores),
            "mean": aggregation.mean_score(item_scores),
            "note_count": len(item_scores),
        }
        evidence_by_item[item.id] = [
            s.evidence_span for s in item_scores if s.evidence_span
        ]

    note_count = len({s.note_id for s in scores})

    user = load_prompt("monthly.txt").format(
        month=month,
        event_type=event_type,
        note_count=note_count,
        score_table=_format_score_table(rows_for_prompt),
        evidence_by_item=_format_evidence(evidence_by_item),
    )
    llm_response = llm.complete(_SYSTEM, user, _MonthlyLLMResponse)
    assert isinstance(llm_response, _MonthlyLLMResponse)
    narratives_by_id = {n.rubric_item_id: n for n in llm_response.per_item}

    item_summaries: list[RubricItemSummary] = []
    for item in applicable_items:
        item_scores = scores_by_item[item.id]
        if not item_scores:
            continue
        narrative = narratives_by_id.get(item.id)
        qualitative = narrative.qualitative_summary if narrative else ""
        evidence_choices = narrative.representative_evidence if narrative else []
        # Ensure representative_evidence is a subset of the spans we passed in.
        allowed = set(evidence_by_item[item.id])
        rep_evidence = [e for e in evidence_choices if e in allowed][:3]
        if not rep_evidence:
            rep_evidence = evidence_by_item[item.id][:3]

        item_summaries.append(
            RubricItemSummary(
                rubric_item_id=item.id,
                score_distribution=aggregation.score_distribution(item_scores),
                mean_score=aggregation.mean_score(item_scores),
                note_count=len(item_scores),
                qualitative_summary=qualitative,
                representative_evidence=rep_evidence,
            )
        )

    return MonthlySummary(
        author_id=author_id,
        event_type=event_type,
        month=month,
        rubric_item_summaries=item_summaries,
        cross_item_themes=llm_response.cross_item_themes,
        insufficient_evidence_rate=aggregation.insufficient_evidence_rate(scores),
    )
