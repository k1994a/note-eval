from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Hashable
from datetime import UTC, datetime, timedelta

from .schemas.score import Score

IMPROVEMENT_THRESHOLD = 0.3
WEAK_THRESHOLD = 1.0


def _parse_dt(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def month_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m")


def recent_window_start(now: datetime, days: int = 30) -> datetime:
    return now - timedelta(days=days)


def filter_scorable(scores: list[Score]) -> list[Score]:
    return [s for s in scores if s.score != "insufficient_evidence"]


def score_distribution(scores: list[Score]) -> dict[str, int]:
    buckets: dict[str, int] = {"0": 0, "1": 0, "2": 0, "insufficient_evidence": 0}
    for s in scores:
        buckets[str(s.score)] += 1
    return buckets


def mean_score(scores: list[Score]) -> float | None:
    scorable = filter_scorable(scores)
    if not scorable:
        return None
    total = sum(int(s.score) for s in scorable)
    return total / len(scorable)


def insufficient_evidence_rate(scores: list[Score]) -> float:
    if not scores:
        return 0.0
    insufficient = sum(1 for s in scores if s.score == "insufficient_evidence")
    return insufficient / len(scores)


def group_by(scores: list[Score], key: Callable[[Score], Hashable]) -> dict[Hashable, list[Score]]:
    out: dict[Hashable, list[Score]] = defaultdict(list)
    for s in scores:
        out[key(s)].append(s)
    return dict(out)


def build_score_table(scores: list[Score]) -> dict[tuple[str, str, str, str], list[Score]]:
    """Key: (author_id, event_type, rubric_item_id, month_key)."""
    table: dict[tuple[str, str, str, str], list[Score]] = defaultdict(list)
    for s in scores:
        mk = month_key(_parse_dt(s.occurred_at))
        table[(s.author_id, s.event_type, s.rubric_item_id, mk)].append(s)
    return dict(table)


def compute_direction(
    monthly_means: dict[str, float | None],
    improvement_threshold: float = IMPROVEMENT_THRESHOLD,
) -> str:
    """Compare first and last non-None months chronologically."""
    months = sorted(monthly_means.keys())
    non_null = [(m, monthly_means[m]) for m in months if monthly_means[m] is not None]
    if len(non_null) < 2:
        return "insufficient_data"
    first = non_null[0][1]
    last = non_null[-1][1]
    delta = last - first  # type: ignore[operator]
    if delta >= improvement_threshold:
        return "improving"
    if delta <= -improvement_threshold:
        return "declining"
    return "flat"
