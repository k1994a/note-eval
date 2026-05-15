from __future__ import annotations

import json

from pydantic import BaseModel

from .. import aggregation
from ..llm import LLMClient
from ..schemas.summary import MonthlySummary, RubricItemTrend, Trend
from ._prompts import load_prompt

_SYSTEM = "You narrate monthly trends faithfully against computed means. Return structured JSON."


class _TrendItemNarrative(BaseModel):
    rubric_item_id: str
    trend_narrative: str


class _TrendLLMResponse(BaseModel):
    per_item: list[_TrendItemNarrative]
    overall_summary: str


def _collect_monthly_means(
    monthly_summaries: list[MonthlySummary],
) -> dict[str, dict[str, float | None]]:
    """Returns rubric_item_id -> {month: mean}."""
    out: dict[str, dict[str, float | None]] = {}
    for ms in monthly_summaries:
        for item_summary in ms.rubric_item_summaries:
            out.setdefault(item_summary.rubric_item_id, {})[ms.month] = item_summary.mean_score
    return out


def analyze_trend(
    author_id: str,
    event_type: str,
    monthly_summaries: list[MonthlySummary],
    llm: LLMClient,
) -> Trend:
    means_by_item = _collect_monthly_means(monthly_summaries)
    directions = {
        item_id: aggregation.compute_direction(means)
        for item_id, means in means_by_item.items()
    }

    monthly_context = [
        {
            "month": ms.month,
            "cross_item_themes": ms.cross_item_themes,
            "per_item": [
                {
                    "rubric_item_id": s.rubric_item_id,
                    "mean": s.mean_score,
                    "summary": s.qualitative_summary,
                }
                for s in ms.rubric_item_summaries
            ],
        }
        for ms in sorted(monthly_summaries, key=lambda m: m.month)
    ]

    user = load_prompt("trend.txt").format(
        monthly_means_table=json.dumps(means_by_item, indent=2, default=str),
        directions=json.dumps(directions, indent=2),
        monthly_summaries=json.dumps(monthly_context, indent=2, default=str),
    )

    llm_response = llm.complete(_SYSTEM, user, _TrendLLMResponse)
    assert isinstance(llm_response, _TrendLLMResponse)
    narrative_by_id = {n.rubric_item_id: n.trend_narrative for n in llm_response.per_item}

    per_item: list[RubricItemTrend] = []
    for item_id, means in sorted(means_by_item.items()):
        per_item.append(
            RubricItemTrend(
                rubric_item_id=item_id,
                monthly_means=means,
                direction=directions[item_id],  # type: ignore[arg-type]
                trend_narrative=narrative_by_id.get(item_id, ""),
            )
        )

    return Trend(
        author_id=author_id,
        event_type=event_type,
        per_rubric_item=per_item,
        overall_summary=llm_response.overall_summary,
    )
