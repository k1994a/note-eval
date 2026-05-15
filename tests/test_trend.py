from __future__ import annotations

from note_eval import aggregation
from note_eval.agents.monthly import summarize_month
from note_eval.agents.scorer import score_notes
from note_eval.agents.trend import analyze_trend


def _build_monthly_summaries(sample_notes, sample_rubric, mock_llm, tmp_cache, author_id, event_type):
    scores = score_notes(sample_notes, sample_rubric, mock_llm, tmp_cache)
    notes_by_id = {n.note_id: n for n in sample_notes}
    months = sorted({s.occurred_at[:7] for s in scores if s.author_id == author_id and s.event_type == event_type})
    monthly_summaries = []
    for month in months:
        slice_scores = [
            s
            for s in scores
            if s.author_id == author_id
            and s.event_type == event_type
            and s.occurred_at.startswith(month)
        ]
        monthly_summaries.append(
            summarize_month(
                author_id=author_id,
                event_type=event_type,
                month=month,
                scores=slice_scores,
                notes_by_id=notes_by_id,
                rubric=sample_rubric,
                llm=mock_llm,
            )
        )
    return monthly_summaries


def test_directions_match_aggregation(sample_notes, sample_rubric, mock_llm, tmp_cache):
    summaries = _build_monthly_summaries(
        sample_notes, sample_rubric, mock_llm, tmp_cache, "author_001", "type_a"
    )
    if not summaries:
        return
    trend = analyze_trend("author_001", "type_a", summaries, mock_llm)

    means_by_item: dict[str, dict[str, float | None]] = {}
    for ms in summaries:
        for r in ms.rubric_item_summaries:
            means_by_item.setdefault(r.rubric_item_id, {})[ms.month] = r.mean_score

    for item_trend in trend.per_rubric_item:
        expected = aggregation.compute_direction(means_by_item[item_trend.rubric_item_id])
        assert item_trend.direction == expected


def test_trend_has_narrative_per_present_item(sample_notes, sample_rubric, mock_llm, tmp_cache):
    summaries = _build_monthly_summaries(
        sample_notes, sample_rubric, mock_llm, tmp_cache, "author_001", "type_a"
    )
    if not summaries:
        return
    trend = analyze_trend("author_001", "type_a", summaries, mock_llm)
    item_ids_in_summaries: set[str] = set()
    for ms in summaries:
        for r in ms.rubric_item_summaries:
            item_ids_in_summaries.add(r.rubric_item_id)
    assert {it.rubric_item_id for it in trend.per_rubric_item} == item_ids_in_summaries
