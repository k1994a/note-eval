from __future__ import annotations

import json
from datetime import UTC, datetime

from note_eval.ingestion import generate_synthetic, load_notes, load_rubric
from note_eval.llm import MockLLMClient
from note_eval.pipeline import run_pipeline
from note_eval.schemas.report import AuthorReport
from note_eval.storage.cache import Cache


def test_pipeline_end_to_end(tmp_path):
    end = datetime(2026, 5, 1, tzinfo=UTC)
    notes_path = generate_synthetic(
        authors=3,
        days=90,
        out_dir=tmp_path,
        seed=42,
        end_date=end,
        rubric_path="data/rubric.json",
    )
    notes = load_notes(notes_path)
    rubric = load_rubric("data/rubric.json")
    llm = MockLLMClient()
    cache = Cache(tmp_path / "cache")
    now = datetime(2026, 5, 1, tzinfo=UTC)

    reports = run_pipeline(notes, rubric, llm, cache, now)
    authors = {n.author_id for n in notes}
    assert set(reports.keys()) == authors

    for author_id, report in reports.items():
        assert isinstance(report, AuthorReport)
        assert report.by_event_type
        for et, etr in report.by_event_type.items():
            assert etr.event_type == et
            assert et in rubric.event_types()
            assert etr.last_30_days is not None
            assert etr.trend is not None
            assert etr.monthly_summaries

        # JSON round-trip
        payload = report.model_dump_json()
        loaded = AuthorReport.model_validate_json(payload)
        assert loaded.author_id == author_id
        json.loads(payload)  # ensures valid JSON
