from __future__ import annotations

from note_eval.schemas.score import Score
from note_eval.storage.cache import Cache


def _score(value=1) -> Score:
    return Score(
        note_id="n1",
        author_id="a1",
        event_type="type_a",
        occurred_at="2026-01-15T12:00:00+00:00",
        rubric_item_id="item_001",
        rubric_version="1.0.0",
        score=value,
        evidence_span="evidence",
        rationale="r",
        confidence="high",
    )


def test_get_missing_returns_none(tmp_cache):
    assert tmp_cache.get("does-not-exist") is None


def test_set_then_get_round_trip(tmp_cache):
    key = Cache.make_key("n1", "item_001", "1.0.0")
    tmp_cache.set(key, _score())
    out = tmp_cache.get(key)
    assert out is not None
    assert out.rubric_item_id == "item_001"
    assert out.score == 1


def test_clear_empties_cache(tmp_cache):
    key = Cache.make_key("n1", "item_001", "1.0.0")
    tmp_cache.set(key, _score())
    tmp_cache.clear()
    assert tmp_cache.get(key) is None
