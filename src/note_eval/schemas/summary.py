from typing import Literal

from pydantic import BaseModel, field_validator


class RubricItemSummary(BaseModel):
    rubric_item_id: str
    score_distribution: dict[str, int]
    mean_score: float | None
    note_count: int
    qualitative_summary: str
    representative_evidence: list[str]


class MonthlySummary(BaseModel):
    author_id: str
    event_type: str
    month: str
    rubric_item_summaries: list[RubricItemSummary]
    cross_item_themes: str
    insufficient_evidence_rate: float


class RubricItemTrend(BaseModel):
    rubric_item_id: str
    monthly_means: dict[str, float | None]
    direction: Literal["improving", "declining", "flat", "insufficient_data"]
    trend_narrative: str


class Trend(BaseModel):
    author_id: str
    event_type: str
    per_rubric_item: list[RubricItemTrend]
    overall_summary: str


class RecentSummary(BaseModel):
    author_id: str
    event_type: str
    window_start: str
    window_end: str
    improving: list[str]
    declining: list[str]
    persistently_weak: list[str]

    @field_validator("improving", "declining", "persistently_weak")
    @classmethod
    def _exactly_two(cls, v: list[str]) -> list[str]:
        if len(v) != 2:
            raise ValueError("must contain exactly 2 bullets")
        return v
