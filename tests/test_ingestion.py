from __future__ import annotations

from datetime import UTC, datetime

from note_eval.ingestion import generate_synthetic, load_notes


def test_load_rubric(tmp_path, sample_rubric):
    assert sample_rubric.version == "1.0.0"
    assert len(sample_rubric.items) >= 1
    event_types = sample_rubric.event_types()
    assert "type_a" in event_types


def test_load_notes_sorts_by_occurred_at(tmp_path):
    payload = (
        '[{"note_id":"b","author_id":"a","subject_id":"s","event_type":"type_a",'
        '"occurred_at":"2026-02-15T00:00:00+00:00","text":"second"},'
        '{"note_id":"a","author_id":"a","subject_id":"s","event_type":"type_a",'
        '"occurred_at":"2026-01-15T00:00:00+00:00","text":"first"}]'
    )
    path = tmp_path / "notes.json"
    path.write_text(payload)
    notes = load_notes(path)
    assert [n.note_id for n in notes] == ["a", "b"]


def test_generate_synthetic_round_trips(tmp_path):
    end = datetime(2026, 5, 1, tzinfo=UTC)
    path = generate_synthetic(
        authors=3,
        days=20,
        out_dir=tmp_path,
        seed=42,
        end_date=end,
        rubric_path="data/rubric.json",
    )
    assert path.exists()
    notes = load_notes(path)
    assert notes, "expected at least one synthetic note"
    authors = {n.author_id for n in notes}
    assert authors == {"author_001", "author_002", "author_003"}

    # Date span fits within the requested window.
    occurred = [n.occurred_at for n in notes]
    earliest = min(occurred)
    latest = max(occurred)
    assert earliest >= end - __import__("datetime").timedelta(days=20)
    assert latest <= end + __import__("datetime").timedelta(days=1)


def test_generate_synthetic_event_types_in_rubric(tmp_path, sample_rubric):
    end = datetime(2026, 5, 1, tzinfo=UTC)
    path = generate_synthetic(
        authors=2,
        days=10,
        out_dir=tmp_path,
        seed=1,
        end_date=end,
        rubric_path="data/rubric.json",
    )
    notes = load_notes(path)
    allowed = set(sample_rubric.event_types())
    for n in notes:
        assert n.event_type in allowed
