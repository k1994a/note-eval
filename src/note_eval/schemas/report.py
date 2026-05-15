from pydantic import BaseModel

from .score import Score
from .summary import MonthlySummary, RecentSummary, Trend


class EventTypeReport(BaseModel):
    event_type: str
    monthly_summaries: list[MonthlySummary]
    trend: Trend
    last_30_days: RecentSummary
    score_table: list[Score]


class AuthorReport(BaseModel):
    author_id: str
    rubric_version: str
    generated_at: str
    by_event_type: dict[str, EventTypeReport]
