from __future__ import annotations

import json
from datetime import UTC, datetime

from pydantic import BaseModel, field_validator

from .. import aggregation
from ..llm import LLMClient
from ..schemas.score import Score
from ..schemas.summary import MonthlySummary, RecentSummary
from ._prompts import load_prompt

_SYSTEM = "You summarize the last 30 days. Always return exactly two bullets per category."


class _RecentLLMResponse(BaseModel):
    improving: list[str]
    declining: list[str]
    persistently_weak: list[str]

    @field_validator("improving", "declining", "persistently_weak")
    @classmethod
    def _exactly_two(cls, v: list[str]) -> list[str]:
        if len(v) != 2:
            raise ValueError("must contain exactly 2 bullets")
        return v


def _parse(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def summarize_recent(
    author_id: str,
    event_type: str,
    monthly_summaries: list[MonthlySummary],
    scores: list[Score],
    now: datetime,
    llm: LLMClient,
) -> RecentSummary:
    start = aggregation.recent_window_start(now)
    in_window = [s for s in scores if start <= _parse(s.occurred_at) <= now]

    # Score-table summary per rubric item for the window
    by_item: dict[str, list[Score]] = {}
    for s in in_window:
        by_item.setdefault(s.rubric_item_id, []).append(s)
    score_table = {
        item_id: {
            "distribution": aggregation.score_distribution(item_scores),
            "mean": aggregation.mean_score(item_scores),
            "note_count": len(item_scores),
        }
        for item_id, item_scores in sorted(by_item.items())
    }

    window_months = {start.strftime("%Y-%m"), now.strftime("%Y-%m")}
    overlapping = [
        {
            "month": ms.month,
            "cross_item_themes": ms.cross_item_themes,
            "per_item": [
                {"rubric_item_id": s.rubric_item_id, "mean": s.mean_score}
                for s in ms.rubric_item_summaries
            ],
        }
        for ms in monthly_summaries
        if ms.month in window_months
    ]

    user = load_prompt("recent.txt").format(
        window_start=start.isoformat(),
        window_end=now.isoformat(),
        note_count=len({s.note_id for s in in_window}),
        score_table=json.dumps(score_table, indent=2, default=str),
        monthly_summaries=json.dumps(overlapping, indent=2, default=str),
    )

    response = llm.complete(_SYSTEM, user, _RecentLLMResponse)
    assert isinstance(response, _RecentLLMResponse)

    return RecentSummary(
        author_id=author_id,
        event_type=event_type,
        window_start=start.isoformat(),
        window_end=now.isoformat(),
        improving=response.improving,
        declining=response.declining,
        persistently_weak=response.persistently_weak,
    )
