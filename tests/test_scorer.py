from __future__ import annotations

from datetime import UTC, datetime

from note_eval.agents.scorer import score_note_item, score_notes
from note_eval.llm import MockLLMClient
from note_eval.schemas.note import Note
from note_eval.schemas.score import Score


def _note(text: str, event_type: str = "type_a", note_id: str = "n1") -> Note:
    return Note(
        note_id=note_id,
        author_id="a1",
        subject_id="s1",
        event_type=event_type,
        occurred_at=datetime(2026, 1, 15, tzinfo=UTC),
        text=text,
    )


def test_scorer_returns_valid_score(sample_rubric, mock_llm, tmp_cache):
    item = sample_rubric.items[0]
    note = _note("Alex shared the missed Tuesday deadline and named owners.")
    score = score_note_item(note, item, sample_rubric.version, mock_llm, tmp_cache)
    assert isinstance(score, Score)
    assert score.note_id == note.note_id
    assert score.rubric_item_id == item.id
    assert score.rubric_version == sample_rubric.version


def test_empty_note_is_skipped(sample_rubric, mock_llm, tmp_cache):
    empty = _note("   ")
    full = _note("Alex shared the deadline and called out owners.", note_id="n2")
    scores = score_notes([empty, full], sample_rubric, mock_llm, tmp_cache)
    assert all(s.note_id != "n1" for s in scores)
    assert any(s.note_id == "n2" for s in scores)


def test_non_applicable_items_not_scored(sample_rubric, mock_llm, tmp_cache):
    # item_004 only applies to type_c
    note = _note("body", event_type="type_a")
    scores = score_notes([note], sample_rubric, mock_llm, tmp_cache)
    scored_item_ids = {s.rubric_item_id for s in scores}
    assert "item_004" not in scored_item_ids


def test_cache_hit_on_second_call(sample_rubric, tmp_cache):
    class CountingClient:
        def __init__(self):
            self.calls = 0
            self._inner = MockLLMClient()

        def complete(self, system, user, response_model):
            self.calls += 1
            return self._inner.complete(system, user, response_model)

    llm = CountingClient()
    item = sample_rubric.items[0]
    note = _note("Alex shared the missed Tuesday deadline and named owners.")
    score_note_item(note, item, sample_rubric.version, llm, tmp_cache)
    assert llm.calls == 1
    score_note_item(note, item, sample_rubric.version, llm, tmp_cache)
    assert llm.calls == 1, "second call should be served from cache"
