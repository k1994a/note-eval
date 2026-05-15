from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from ..schemas.note import Note
from ..schemas.score import Score


class NoteRepository(Protocol):
    def get_notes(
        self,
        author_id: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Note]: ...

    def save_scores(self, scores: list[Score]) -> None: ...

    def get_scores(
        self,
        author_id: str,
        event_type: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Score]: ...


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


class JSONFileRepository:
    """Reads notes from one JSON file, persists scores to another.

    For sample data and tests. Real DB-backed implementations satisfy
    NoteRepository and can replace this class.
    """

    def __init__(self, notes_path: str, scores_path: str):
        self._notes_path = Path(notes_path)
        self._scores_path = Path(scores_path)

    def get_notes(
        self,
        author_id: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Note]:
        if not self._notes_path.exists():
            return []
        raw = json.loads(self._notes_path.read_text())
        notes = [Note.model_validate(n) for n in raw]
        if author_id is not None:
            notes = [n for n in notes if n.author_id == author_id]
        if start is not None:
            s = _aware(start)
            notes = [n for n in notes if _aware(n.occurred_at) >= s]
        if end is not None:
            e = _aware(end)
            notes = [n for n in notes if _aware(n.occurred_at) < e]
        return notes

    def save_scores(self, scores: list[Score]) -> None:
        existing: list[dict] = []
        if self._scores_path.exists():
            existing = json.loads(self._scores_path.read_text())
        existing.extend(s.model_dump() for s in scores)
        self._scores_path.parent.mkdir(parents=True, exist_ok=True)
        self._scores_path.write_text(json.dumps(existing, indent=2, default=str))

    def get_scores(
        self,
        author_id: str,
        event_type: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Score]:
        if not self._scores_path.exists():
            return []
        raw = json.loads(self._scores_path.read_text())
        scores = [Score.model_validate(s) for s in raw if s.get("author_id") == author_id]
        if event_type is not None:
            scores = [s for s in scores if s.event_type == event_type]

        def _parse(ts: str) -> datetime:
            return _aware(datetime.fromisoformat(ts.replace("Z", "+00:00")))

        if start is not None:
            s_dt = _aware(start)
            scores = [s for s in scores if _parse(s.occurred_at) >= s_dt]
        if end is not None:
            e_dt = _aware(end)
            scores = [s for s in scores if _parse(s.occurred_at) < e_dt]
        return scores
