from __future__ import annotations

import hashlib
from pathlib import Path

from ..schemas.score import Score


class Cache:
    """Content-addressed JSON cache for scoring results.

    Key = SHA-256(note_id|rubric_item_id|rubric_version). Each entry lives
    as one JSON file under ``root`` (default ``.cache/``).
    """

    def __init__(self, root: str | Path = ".cache"):
        self._root = Path(root)

    @staticmethod
    def make_key(note_id: str, rubric_item_id: str, rubric_version: str) -> str:
        material = f"{note_id}|{rubric_item_id}|{rubric_version}".encode()
        return hashlib.sha256(material).hexdigest()

    def _path(self, key: str) -> Path:
        return self._root / f"{key}.json"

    def get(self, key: str) -> Score | None:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            return Score.model_validate_json(path.read_text())
        except Exception:
            return None

    def set(self, key: str, score: Score) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        self._path(key).write_text(score.model_dump_json())

    def clear(self) -> None:
        if not self._root.exists():
            return
        for child in self._root.iterdir():
            if child.is_file():
                child.unlink()
