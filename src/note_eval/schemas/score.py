from typing import Literal

from pydantic import BaseModel

ScoreValue = Literal[0, 1, 2] | Literal["insufficient_evidence"]


class Score(BaseModel):
    note_id: str
    author_id: str
    event_type: str
    occurred_at: str
    rubric_item_id: str
    rubric_version: str
    score: ScoreValue
    evidence_span: str
    rationale: str
    confidence: Literal["high", "low"]
