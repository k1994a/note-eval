from __future__ import annotations

from datetime import UTC, datetime

from note_eval.agents.recent import summarize_recent
from note_eval.agents.scorer import score_notes


def test_recent_exactly_two_bullets_each(sample_notes, sample_rubric, mock_llm, tmp_cache):
    scores = score_notes(sample_notes, sample_rubric, mock_llm, tmp_cache)
    now = datetime(2026, 5, 14, tzinfo=UTC)
    result = summarize_recent(
        author_id="author_001",
        event_type="type_a",
        monthly_summaries=[],
        scores=[s for s in scores if s.author_id == "author_001" and s.event_type == "type_a"],
        now=now,
        llm=mock_llm,
    )
    assert len(result.improving) == 2
    assert len(result.declining) == 2
    assert len(result.persistently_weak) == 2


def test_recent_window_bounded_to_30_days(sample_notes, sample_rubric, mock_llm, tmp_cache):
    scores = score_notes(sample_notes, sample_rubric, mock_llm, tmp_cache)
    now = datetime(2026, 5, 14, tzinfo=UTC)
    result = summarize_recent(
        author_id="author_001",
        event_type="type_a",
        monthly_summaries=[],
        scores=[s for s in scores if s.author_id == "author_001" and s.event_type == "type_a"],
        now=now,
        llm=mock_llm,
    )
    window_start = datetime.fromisoformat(result.window_start)
    delta = now - window_start
    assert delta.days == 30
