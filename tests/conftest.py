from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from note_eval.ingestion import load_rubric
from note_eval.llm import MockLLMClient
from note_eval.schemas.note import Note
from note_eval.storage.cache import Cache

REPO_ROOT = Path(__file__).resolve().parents[1]
RUBRIC_PATH = REPO_ROOT / "data" / "rubric.json"


@pytest.fixture
def sample_rubric():
    return load_rubric(RUBRIC_PATH)


@pytest.fixture
def mock_llm():
    return MockLLMClient()


@pytest.fixture
def tmp_cache(tmp_path):
    return Cache(tmp_path / "cache")


@pytest.fixture
def sample_notes(sample_rubric):
    """Six notes across three event types and three months."""
    base = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
    notes: list[Note] = []
    for i, month_offset in enumerate([0, 30, 60, 0, 30, 60]):
        event_type = ["type_a", "type_b", "type_c"][i % 3]
        notes.append(
            Note(
                note_id=f"note_{i+1:03d}",
                author_id=f"author_{(i % 2) + 1:03d}",
                subject_id="subject_001",
                event_type=event_type,
                occurred_at=base + timedelta(days=month_offset, hours=i),
                text=(
                    "Alex shared the missed Tuesday deadline and walked through the "
                    "rework plan with named owners. I asked Sam to draft the proposal "
                    "by Friday and confirmed alignment by inviting them to restate the "
                    "agreement in their own words. Recap: covered three topics."
                ),
            )
        )
    return notes
