from __future__ import annotations

from note_eval import aggregation
from note_eval.agents.monthly import summarize_month
from note_eval.agents.scorer import score_notes


def test_monthly_summary_has_one_summary_per_applicable_item(
    sample_notes, sample_rubric, mock_llm, tmp_cache
):
    scores = score_notes(sample_notes, sample_rubric, mock_llm, tmp_cache)

    # Pick one (author, event_type, month) slice with at least one score
    target = scores[0]
    month = target.occurred_at[:7]
    slice_scores = [
        s
        for s in scores
        if s.author_id == target.author_id
        and s.event_type == target.event_type
        and s.occurred_at.startswith(month)
    ]
    notes_by_id = {n.note_id: n for n in sample_notes}

    summary = summarize_month(
        author_id=target.author_id,
        event_type=target.event_type,
        month=month,
        scores=slice_scores,
        notes_by_id=notes_by_id,
        rubric=sample_rubric,
        llm=mock_llm,
    )

    item_ids_with_scores = {s.rubric_item_id for s in slice_scores}
    summary_item_ids = {r.rubric_item_id for r in summary.rubric_item_summaries}
    assert summary_item_ids == item_ids_with_scores
    # Insufficient_evidence_rate matches deterministic computation
    assert summary.insufficient_evidence_rate == aggregation.insufficient_evidence_rate(slice_scores)
