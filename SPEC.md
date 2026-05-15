# Claude Code Build Spec: note-eval

This document is the implementation specification. Read it top-to-bottom before writing code. Every section below describes one file or module. Implement in the order listed.

## Project goals

Build a LangGraph pipeline that:

1. Scores free-text notes against a rubric (JSON-defined, event-type-aware).
2. Aggregates scores deterministically into a time-sliced table.
3. Produces per-author qualitative narratives: monthly summaries, month-over-month trends, last-30-day summaries.

## Non-goals

- Authentication, multi-tenancy, deployment scaffolding.
- UI / API server (this is a library + CLI).
- Real database integration (storage is a Protocol with JSON-file default).

## Stack

- Python 3.11+
- LangGraph for orchestration
- OpenAI Python SDK for LLM calls (mockable)
- Pydantic v2 for schemas
- pytest for tests
- No CI

## Repository layout

```
note-eval/
├── LICENSE
├── README.md
├── DOUBTS.md
├── SPEC.md                          # this file
├── pyproject.toml
├── .gitignore
├── data/
│   ├── rubric.json                  # example rubric
│   └── samples/                     # generated synthetic data
├── src/
│   └── note_eval/
│       ├── __init__.py
│       ├── cli.py                   # entry point
│       ├── ingestion.py             # note + rubric loading, synthetic data gen
│       ├── pipeline.py              # LangGraph wiring
│       ├── aggregation.py           # deterministic table builders
│       ├── llm.py                   # OpenAI client wrapper (mock + live)
│       ├── schemas/
│       │   ├── __init__.py
│       │   ├── note.py
│       │   ├── rubric.py
│       │   ├── score.py
│       │   ├── summary.py
│       │   └── report.py
│       ├── agents/
│       │   ├── __init__.py
│       │   ├── scorer.py            # Agent 1
│       │   ├── monthly.py           # Agent 2
│       │   ├── trend.py             # Agent 3
│       │   └── recent.py            # Agent 4
│       ├── prompts/
│       │   ├── scorer.txt
│       │   ├── monthly.txt
│       │   ├── trend.txt
│       │   └── recent.txt
│       └── storage/
│           ├── __init__.py
│           ├── repository.py        # Protocol + JSON-file impl
│           └── cache.py             # content-addressed cache
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── test_aggregation.py
    ├── test_ingestion.py
    ├── test_scorer.py
    ├── test_monthly.py
    ├── test_trend.py
    ├── test_recent.py
    ├── test_pipeline.py
    └── test_cache.py
```

## Schemas (Pydantic v2)

### `schemas/note.py`

```python
from datetime import datetime
from pydantic import BaseModel

class Note(BaseModel):
    note_id: str
    author_id: str
    subject_id: str          # the person being written about
    event_type: str
    occurred_at: datetime    # UTC
    text: str
```

### `schemas/rubric.py`

```python
from pydantic import BaseModel
from typing import Literal

class RubricAnchors(BaseModel):
    score_0: str
    score_1: str
    score_2: str

class RubricItem(BaseModel):
    id: str
    name: str
    description: str
    applies_to_event_types: list[str]
    anchors: RubricAnchors

class Rubric(BaseModel):
    version: str
    items: list[RubricItem]

    def items_for_event_type(self, event_type: str) -> list[RubricItem]:
        return [i for i in self.items if event_type in i.applies_to_event_types]
```

### `schemas/score.py`

```python
from typing import Literal
from pydantic import BaseModel

ScoreValue = Literal[0, 1, 2, "insufficient_evidence"]

class Score(BaseModel):
    note_id: str
    author_id: str
    event_type: str
    occurred_at: str        # ISO 8601 UTC
    rubric_item_id: str
    rubric_version: str
    score: ScoreValue
    evidence_span: str      # verbatim quote, "" if insufficient_evidence
    rationale: str
    confidence: Literal["high", "low"]
```

### `schemas/summary.py`

```python
from pydantic import BaseModel

class RubricItemSummary(BaseModel):
    rubric_item_id: str
    score_distribution: dict[str, int]      # {"0": n, "1": n, "2": n, "insufficient_evidence": n}
    mean_score: float | None
    note_count: int
    qualitative_summary: str
    representative_evidence: list[str]

class MonthlySummary(BaseModel):
    author_id: str
    event_type: str
    month: str                              # "YYYY-MM"
    rubric_item_summaries: list[RubricItemSummary]
    cross_item_themes: str
    insufficient_evidence_rate: float

class RubricItemTrend(BaseModel):
    rubric_item_id: str
    monthly_means: dict[str, float | None]  # {"YYYY-MM": mean}
    direction: Literal["improving", "declining", "flat", "insufficient_data"]
    trend_narrative: str

class Trend(BaseModel):
    author_id: str
    event_type: str
    per_rubric_item: list[RubricItemTrend]
    overall_summary: str

class RecentSummary(BaseModel):
    author_id: str
    event_type: str
    window_start: str                       # ISO 8601 UTC
    window_end: str
    improving: list[str]                    # 2 bullets
    declining: list[str]                    # 2 bullets
    persistently_weak: list[str]            # 2 bullets
```

### `schemas/report.py`

```python
from pydantic import BaseModel
from .summary import MonthlySummary, Trend, RecentSummary
from .score import Score

class EventTypeReport(BaseModel):
    event_type: str
    monthly_summaries: list[MonthlySummary]
    trend: Trend
    last_30_days: RecentSummary
    score_table: list[Score]                # raw scores for drill-down

class AuthorReport(BaseModel):
    author_id: str
    rubric_version: str
    generated_at: str
    by_event_type: dict[str, EventTypeReport]
```

## LLM client (`llm.py`)

Two modes: `mock` (default) and `live`. Selected by `NOTE_EVAL_LLM_MODE` env var.

```python
import os
import hashlib
import json
from typing import Any, Protocol
from pydantic import BaseModel

MAX_CONCURRENT_LLM_CALLS = 10

class LLMClient(Protocol):
    def complete(self, system: str, user: str, response_model: type[BaseModel]) -> BaseModel: ...

class MockLLMClient:
    """Deterministic mock based on hash of inputs.

    Returns a valid instance of response_model with field values seeded by
    the hash of (system + user). For Score, picks 0/1/2 deterministically.
    For text fields, returns short canned strings."""

    def complete(self, system: str, user: str, response_model: type[BaseModel]) -> BaseModel:
        seed = int(hashlib.sha256((system + user).encode()).hexdigest(), 16)
        return _build_mock(response_model, seed, user)

class LiveOpenAIClient:
    """Wraps openai.OpenAI with structured outputs via response_format=BaseModel.

    Retries with exponential backoff on 429/500. Respects MAX_CONCURRENT_LLM_CALLS
    via a semaphore (use threading.Semaphore; callers may run in a thread pool)."""

    def __init__(self, model: str = "gpt-4o-mini"):
        from openai import OpenAI
        self._client = OpenAI()
        self._model = model

    def complete(self, system: str, user: str, response_model: type[BaseModel]) -> BaseModel:
        # use beta.chat.completions.parse for structured output
        ...

def get_client() -> LLMClient:
    mode = os.getenv("NOTE_EVAL_LLM_MODE", "mock")
    return LiveOpenAIClient() if mode == "live" else MockLLMClient()
```

`_build_mock` must produce a valid response_model instance. For `Score`, derive `score` from `seed % 4` mapped to `[0, 1, 2, "insufficient_evidence"]`, with `"insufficient_evidence"` appearing ~15% of the time (use `seed % 100 < 15`). Evidence span: first sentence of `user`. Rationale: "Mock rationale based on note content." Confidence: "high" if `seed % 5 != 0` else "low".

For free-text response models (summaries, trends), produce short coherent stubs derived from input keywords.

## Storage

### `storage/repository.py`

```python
from typing import Protocol
from ..schemas.note import Note
from ..schemas.score import Score

class NoteRepository(Protocol):
    def get_notes(self, author_id: str | None = None,
                  start: datetime | None = None,
                  end: datetime | None = None) -> list[Note]: ...
    def save_scores(self, scores: list[Score]) -> None: ...
    def get_scores(self, author_id: str, event_type: str | None = None,
                   start: datetime | None = None, end: datetime | None = None) -> list[Score]: ...

class JSONFileRepository:
    """Reads notes from one JSON file, persists scores to another.

    Used for sample data and tests. Real implementations satisfy NoteRepository
    and replace this class."""
    def __init__(self, notes_path: str, scores_path: str): ...
```

### `storage/cache.py`

Content-addressed JSON cache. Key = SHA-256 of (note_id + rubric_item_id + rubric_version). Files live under `.cache/`. Methods: `get(key) -> Score | None`, `set(key, score) -> None`, `clear() -> None`.

## Ingestion (`ingestion.py`)

Three responsibilities:

1. **`load_rubric(path: str) -> Rubric`** — parse JSON to Pydantic.
2. **`load_notes(path: str) -> list[Note]`** — parse JSON to Pydantic, sort by `occurred_at`.
3. **`generate_synthetic(authors: int, days: int, out_dir: str) -> None`** — generate a `notes.json` with realistic-ish variability:
   - Each author writes 0–2 notes per day (Poisson, λ=0.7).
   - Event type sampled from rubric event types with non-uniform weights.
   - Note text length varies: 10% empty-ish (under 50 chars), 60% medium (200–600 chars), 30% long (600–1500 chars).
   - Quality varies per author: each author has a "skill" parameter (0–1) that biases which rubric anchors the synthetic text resembles.
   - Author skill drifts over the 3 months (some up, some down, some flat) so trend analysis has signal.

Synthetic text generation is templated, not LLM-generated. Use sentence templates per rubric item per anchor level, sampled and combined. No company-specific terminology — keep it generic.

CLI subcommand: `python -m note_eval.ingestion generate --authors 5 --days 90 --out data/samples`.

## Aggregation (`aggregation.py`)

Pure functions, no LLM. Heavily unit-tested.

```python
from datetime import datetime, timezone, timedelta
from .schemas.score import Score, ScoreValue

def month_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m")

def recent_window_start(now: datetime, days: int = 30) -> datetime:
    return now - timedelta(days=days)

def filter_scorable(scores: list[Score]) -> list[Score]:
    """Drops insufficient_evidence."""
    return [s for s in scores if s.score != "insufficient_evidence"]

def score_distribution(scores: list[Score]) -> dict[str, int]:
    """All four buckets: '0', '1', '2', 'insufficient_evidence'."""
    ...

def mean_score(scores: list[Score]) -> float | None:
    """Mean over scorable scores; None if no scorable scores."""
    ...

def group_by(scores: list[Score], key) -> dict:
    ...

def build_score_table(scores: list[Score]) -> dict[tuple[str, str, str, str], list[Score]]:
    """Key: (author_id, event_type, rubric_item_id, month_key)."""
    ...

def compute_direction(monthly_means: dict[str, float | None],
                       improvement_threshold: float = 0.3) -> str:
    """Compare first and last non-None month. Returns
    'improving' | 'declining' | 'flat' | 'insufficient_data'."""
    ...

def insufficient_evidence_rate(scores: list[Score]) -> float:
    ...

IMPROVEMENT_THRESHOLD = 0.3
WEAK_THRESHOLD = 1.0
```

## Agents

Each agent module exports a function with this signature:

```python
def run(inputs: <TypedInputs>, llm: LLMClient) -> <OutputModel>: ...
```

Agents do not import each other. Composition happens in `pipeline.py`.

### `agents/scorer.py` (Agent 1)

```python
def score_note_item(note: Note, item: RubricItem, rubric_version: str,
                    llm: LLMClient, cache: Cache) -> Score: ...

def score_notes(notes: list[Note], rubric: Rubric, llm: LLMClient,
                cache: Cache) -> list[Score]:
    """For each note, find applicable rubric items via
    rubric.items_for_event_type(note.event_type), then score each.
    Parallelized via concurrent.futures.ThreadPoolExecutor with
    MAX_CONCURRENT_LLM_CALLS workers. Results cached."""
```

Prompt loading: read `prompts/scorer.txt` once, format with `{rubric_item}`, `{anchors}`, `{note_text}`.

If `note.text.strip()` is empty, skip (return nothing, log warning).

Set `BATCH_MODE = False` constant; if `True`, score all applicable rubric items in one call (return list[Score]). Default off.

### `agents/monthly.py` (Agent 2)

```python
def summarize_month(author_id: str, event_type: str, month: str,
                    scores: list[Score], notes_by_id: dict[str, Note],
                    rubric: Rubric, llm: LLMClient) -> MonthlySummary: ...
```

Compute the score distribution per rubric item using `aggregation.py` (deterministic). Pass the table and the evidence spans to the LLM with the prompt at `prompts/monthly.txt`. LLM produces `qualitative_summary` per rubric item, `cross_item_themes`, and selects 2–3 representative evidence quotes from those passed in.

LLM does not compute counts or means.

### `agents/trend.py` (Agent 3)

```python
def analyze_trend(author_id: str, event_type: str,
                  monthly_summaries: list[MonthlySummary],
                  llm: LLMClient) -> Trend: ...
```

Compute `monthly_means` and `direction` deterministically. LLM writes `trend_narrative` per rubric item (one line each) and `overall_summary` (one line). Prompt: `prompts/trend.txt`.

### `agents/recent.py` (Agent 4)

```python
def summarize_recent(author_id: str, event_type: str,
                     monthly_summaries: list[MonthlySummary],
                     scores: list[Score],
                     now: datetime,
                     llm: LLMClient) -> RecentSummary: ...
```

Filter scores to last 30 days via `aggregation.recent_window_start(now)`. Pass the relevant monthly summaries and the filtered score table to the LLM. Prompt: `prompts/recent.txt`. Output: exactly 2 bullets each in `improving`, `declining`, `persistently_weak`. Validate count in Pydantic.

## Pipeline (`pipeline.py`)

LangGraph wiring. State = a TypedDict with all intermediate artifacts:

```python
from typing import TypedDict
from langgraph.graph import StateGraph, END

class PipelineState(TypedDict):
    notes: list[Note]
    rubric: Rubric
    scores: list[Score]
    monthly_summaries: list[MonthlySummary]
    trends: list[Trend]
    recents: list[RecentSummary]
    reports: dict[str, AuthorReport]
    now: datetime
```

Nodes:

- `score_node` — calls `scorer.score_notes`.
- `monthly_node` — for each (author, event_type, month), calls `monthly.summarize_month`. Use `Send` for parallelism.
- `trend_node` — for each (author, event_type), calls `trend.analyze_trend`. Use `Send`.
- `recent_node` — for each (author, event_type), calls `recent.summarize_recent`. Use `Send`.
- `assemble_node` — combines into `AuthorReport`s.

Edges: `score → monthly → [trend, recent] → assemble → END`. Trend and recent run in parallel.

Expose `run_pipeline(notes, rubric, llm, cache, now) -> dict[str, AuthorReport]`.

## CLI (`cli.py`)

`argparse`-based.

Subcommands:

- `run --notes PATH --rubric PATH --out DIR` — run full pipeline, write one `<author_id>.json` per author to `out/`.
- `calibrate --truth PATH --notes PATH --rubric PATH` — score notes, compare to truth, print per-rubric-item agreement (exact match, within-±1, kappa). Output a `calibration.json`.
- `generate` — proxies to `ingestion.generate_synthetic`.

Use `--llm-mode mock|live` flag, defaulting to env var.

## Prompts

Plain text with `{placeholders}`. Drafted in repo so the user (not the team) can iterate.

### `prompts/scorer.txt`

```
You are an evaluator scoring a single note against a single rubric item.

Rubric item: {rubric_item_name}
Description: {rubric_item_description}

Scoring anchors:
- 0: {anchor_0}
- 1: {anchor_1}
- 2: {anchor_2}

Note text:
"""
{note_text}
"""

Score the note against this rubric item. Use these rules:

- Return 2 only if the note clearly meets the anchor for 2.
- Return 1 if partially present but shallow or lacking specifics.
- Return 0 if not addressed or addressed in a way that fails the anchor.
- Return "insufficient_evidence" if the note is too sparse, ambiguous, or
  off-topic to support any judgment on this item. Do not guess.

Return:
- score: 0, 1, 2, or "insufficient_evidence"
- evidence_span: a verbatim quote from the note that supports your score.
  Empty string if "insufficient_evidence".
- rationale: 1–2 sentences referencing the evidence.
- confidence: "high" if the evidence is unambiguous, "low" otherwise.
```

### `prompts/monthly.txt`

```
You are summarizing one author's performance for one event type in one month.

Month: {month}
Event type: {event_type}
Number of notes this month: {note_count}

The following table shows scores for each rubric item this month:
{score_table}

For each rubric item, here are the evidence spans collected:
{evidence_by_item}

Produce:

1. For each rubric item, a 2–4 sentence qualitative summary describing what
   the author did well or poorly this month. Reference patterns across notes,
   not single quotes. Pick 2–3 representative evidence quotes from those
   provided.

2. A cross_item_themes paragraph (3–5 sentences) describing patterns that
   span multiple rubric items, if any.

Do not compute counts, means, or rates — those are already provided. Narrate them.
Do not invent evidence not present in the spans provided.
```

### `prompts/trend.txt`

```
You are narrating month-over-month trends for one author and one event type.

The following table shows mean scores per rubric item per month:
{monthly_means_table}

Computed directions (improving / declining / flat / insufficient_data) per
rubric item:
{directions}

Monthly summaries for context:
{monthly_summaries}

Produce:

1. For each rubric item, a single-line trend narrative. Reference the direction
   and one concrete reason from the monthly summaries if available.

2. An overall_summary: one line describing the author's overall trajectory
   across rubric items.

Faithfully narrate the computed directions. Do not editorialize or invent
trends not supported by the means.
```

### `prompts/recent.txt`

```
You are summarizing the last 30 days for one author and one event type.

Window: {window_start} to {window_end}
Notes in window: {note_count}

Score table for the window:
{score_table}

Monthly summaries overlapping the window:
{monthly_summaries}

Produce exactly six bullets, two per category:

- improving: 2 specific things getting better in this window.
- declining: 2 specific things getting worse in this window.
- persistently_weak: 2 things that have remained weak across this window.

Each bullet should reference a specific rubric item and be actionable, not
generic. If you cannot find 2 in a category, say "No clear signal" for that
slot — do not invent.
```

## Tests

Use `pytest`. Default to mock LLM (so tests are deterministic, no network).

### `test_aggregation.py`
- `month_key` edge cases (Jan 1 UTC, Dec 31 UTC).
- `score_distribution` with empty input, single score, mixed scores including `insufficient_evidence`.
- `mean_score` excludes insufficient_evidence; returns None when no scorable scores.
- `compute_direction`: improving (+0.5), declining (-0.5), flat (+0.1), insufficient_data (one month missing).
- `recent_window_start` returns correct datetime.

### `test_ingestion.py`
- `load_rubric` from a fixture JSON.
- `load_notes` from a fixture JSON.
- `generate_synthetic` produces a valid `notes.json` parseable by `load_notes`.
- Generated authors span the requested day range.

### `test_scorer.py`
- Scorer returns a valid `Score` for one note + one rubric item.
- Empty note text is skipped.
- Non-applicable rubric items are not scored.
- Cache hit on second call.

### `test_monthly.py`
- Monthly summary contains one `RubricItemSummary` per applicable rubric item with at least one score that month.
- `insufficient_evidence_rate` matches deterministic computation.

### `test_trend.py`
- Directions computed deterministically match `aggregation.compute_direction`.
- Per-item trend narratives produced for all rubric items present in monthly data.

### `test_recent.py`
- Exactly 2 bullets per category.
- Window correctly bounded to last 30 days.

### `test_pipeline.py`
- End-to-end: feed synthetic notes + rubric, get one `AuthorReport` per author.
- Each report has expected event types.
- Output JSON serializes round-trip cleanly.

### `test_cache.py`
- `get` returns None for missing key.
- `set` then `get` returns the same Score.
- `clear` empties the cache.

### `conftest.py`
Provide fixtures: `sample_rubric`, `sample_notes`, `mock_llm`, `tmp_cache`.

## Sample rubric (`data/rubric.json`)

Construct a generic rubric with three event types and ~6 rubric items, some shared across event types, some specific. Anchors should be plausible but not company-specific. Examples of acceptable item names (generic): "captures concrete observations," "balances inquiry and assertion," "specifies next steps with owners," "checks for understanding," "links to prior commitments," "summarizes outcomes." Event types: `type_a`, `type_b`, `type_c`.

## `pyproject.toml`

```toml
[project]
name = "note-eval"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "langgraph>=0.2",
    "openai>=1.40",
    "pydantic>=2.5",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-mock>=3.12"]

[project.scripts]
note-eval = "note_eval.cli:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"
```

## `.gitignore`

```
__pycache__/
*.pyc
.venv/
.cache/
out/
*.egg-info/
.pytest_cache/
.coverage
```

## Build order

1. Schemas (`schemas/*.py`).
2. LLM client (`llm.py`) with mock + live.
3. Storage (`storage/repository.py`, `storage/cache.py`).
4. Ingestion (`ingestion.py`) + sample rubric + synthetic data generator.
5. Aggregation (`aggregation.py`) — pure functions.
6. Prompts (all `prompts/*.txt`).
7. Agents in order: scorer → monthly → trend → recent.
8. Pipeline (`pipeline.py`).
9. CLI (`cli.py`).
10. Tests in the order they're listed above.

## Sanity check before declaring done

- `pip install -e ".[dev]"` succeeds.
- `python -m note_eval.ingestion generate --authors 5 --days 90 --out data/samples` produces valid output.
- `python -m note_eval.cli run --notes data/samples/notes.json --rubric data/rubric.json --out out/` produces one report per author with mock LLM.
- `pytest` passes.
- No real OpenAI calls in tests.
- No company-specific terms anywhere in the repo (grep for any sales/coaching-specific vocabulary and replace with generic).
