from __future__ import annotations

from datetime import UTC, datetime

from note_eval import aggregation
from note_eval.schemas.score import Score


def _score(value, occurred_at: str = "2026-01-15T12:00:00+00:00") -> Score:
    return Score(
        note_id="n1",
        author_id="a1",
        event_type="type_a",
        occurred_at=occurred_at,
        rubric_item_id="item_001",
        rubric_version="1.0.0",
        score=value,
        evidence_span="",
        rationale="r",
        confidence="high",
    )


def test_month_key_year_boundaries():
    assert aggregation.month_key(datetime(2026, 1, 1, tzinfo=UTC)) == "2026-01"
    assert aggregation.month_key(datetime(2026, 12, 31, 23, 59, tzinfo=UTC)) == "2026-12"


def test_score_distribution_empty():
    assert aggregation.score_distribution([]) == {
        "0": 0,
        "1": 0,
        "2": 0,
        "insufficient_evidence": 0,
    }


def test_score_distribution_mixed():
    dist = aggregation.score_distribution(
        [_score(0), _score(1), _score(1), _score(2), _score("insufficient_evidence")]
    )
    assert dist == {"0": 1, "1": 2, "2": 1, "insufficient_evidence": 1}


def test_mean_score_excludes_insufficient():
    assert aggregation.mean_score([_score(0), _score(2)]) == 1.0
    assert aggregation.mean_score([_score("insufficient_evidence")]) is None
    assert aggregation.mean_score([]) is None


def test_compute_direction():
    assert aggregation.compute_direction({"2026-01": 1.0, "2026-02": 1.5}) == "improving"
    assert aggregation.compute_direction({"2026-01": 1.5, "2026-02": 1.0}) == "declining"
    assert aggregation.compute_direction({"2026-01": 1.0, "2026-02": 1.1}) == "flat"
    assert aggregation.compute_direction({"2026-01": None, "2026-02": 1.0}) == "insufficient_data"
    assert aggregation.compute_direction({"2026-01": 1.0}) == "insufficient_data"


def test_recent_window_start():
    now = datetime(2026, 5, 14, tzinfo=UTC)
    assert aggregation.recent_window_start(now).day == 14
    assert aggregation.recent_window_start(now).month == 4


def test_build_score_table_keys():
    table = aggregation.build_score_table(
        [
            _score(0, "2026-01-15T12:00:00+00:00"),
            _score(2, "2026-02-15T12:00:00+00:00"),
        ]
    )
    assert ("a1", "type_a", "item_001", "2026-01") in table
    assert ("a1", "type_a", "item_001", "2026-02") in table


def test_insufficient_evidence_rate():
    assert aggregation.insufficient_evidence_rate([]) == 0.0
    rate = aggregation.insufficient_evidence_rate(
        [_score(0), _score("insufficient_evidence"), _score(1)]
    )
    assert rate == 1 / 3
