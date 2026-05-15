from __future__ import annotations

import argparse
import json
import math
import random
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .schemas.note import Note
from .schemas.rubric import Rubric


def load_rubric(path: str | Path) -> Rubric:
    raw = json.loads(Path(path).read_text())
    return Rubric.model_validate(raw)


def load_notes(path: str | Path) -> list[Note]:
    raw = json.loads(Path(path).read_text())
    notes = [Note.model_validate(n) for n in raw]
    notes.sort(key=lambda n: n.occurred_at)
    return notes


# ---------- synthetic generation ----------

# Per-anchor sentence templates keyed by rubric item id. Generic phrasing —
# no domain-specific vocabulary.
ITEM_TEMPLATES: dict[str, dict[int, list[str]]] = {
    "item_001": {
        0: [
            "Overall the discussion went fine.",
            "They generally seemed engaged today.",
            "Things were mostly okay during the session.",
        ],
        1: [
            "They mentioned a few topics including timelines and scope.",
            "Some specifics came up around the recent project work.",
            "There were brief references to particular items from earlier.",
        ],
        2: [
            "They cited the missed Tuesday deadline and the three open tickets by name.",
            "Concrete examples were shared: the failed dry-run on Monday and the rework on the deployment script.",
            "Specific behaviors observed: arrived prepared with notes, walked through the diagram line by line, and flagged two ambiguities.",
        ],
    },
    "item_002": {
        0: [
            "Told them what to do and moved on.",
            "Directed the next steps without pause.",
            "Walked through the plan with no input invited.",
        ],
        1: [
            "Asked if it sounded okay before continuing.",
            "Checked once whether there were questions.",
            "Paused briefly for a yes/no on the proposal.",
        ],
        2: [
            "Asked what they thought was driving the issue, listened, then offered a counter-hypothesis grounded in their reply.",
            "Solicited their reading of the situation first and built on it before adding a perspective.",
            "Probed the assumption behind their plan and adjusted the suggestion based on what came back.",
        ],
    },
    "item_003": {
        0: [
            "We will revisit this soon.",
            "Said we should try to do better.",
            "Agreed to keep things moving.",
        ],
        1: [
            "They will draft the document next.",
            "Someone will follow up on the open question.",
            "Action item: review the proposal.",
        ],
        2: [
            "Alex will send the revised proposal by Friday; I will review and respond by Monday end-of-day.",
            "Next steps: Priya owns the rollout plan due 2026-06-01; Sam owns the comms draft due 2026-05-25.",
            "I will share the template by Thursday; they will return feedback by next Tuesday at 5pm.",
        ],
    },
    "item_004": {
        0: [
            "Talked through what came up today.",
            "Covered the items on the agenda.",
            "Standalone discussion of current topics.",
        ],
        1: [
            "Briefly noted we had touched on this before.",
            "Mentioned that the topic had come up previously.",
            "Acknowledged this was a recurring theme.",
        ],
        2: [
            "Followed up on the commitment to draft the v2 spec by April — they shared the draft and we walked it through.",
            "Revisited the earlier agreement to pilot the workflow with one team; they reported the pilot ran for three weeks with two outcomes.",
            "Picked up on the promise to bring metrics to this conversation; we reviewed the numbers and compared them to last month's targets.",
        ],
    },
    "item_005": {
        0: [
            "Moved on to the next topic.",
            "Closed the loop and proceeded.",
            "Wrapped up that section.",
        ],
        1: [
            "Asked if that made sense before moving on.",
            "Confirmed they were good with the plan.",
            "Checked: any questions? — no.",
        ],
        2: [
            "Asked them to summarize what we had agreed; their summary matched mine on two points and diverged on one, which we then resolved.",
            "Invited them to walk back through the plan in their own words, which surfaced a missing dependency.",
            "Had them restate the next step and the owner; the restatement caught an incorrect timeline I had assumed.",
        ],
    },
    "item_006": {
        0: [
            "Ended when time ran out.",
            "Wrapped at the top of the hour.",
            "Closed the session and went on.",
        ],
        1: [
            "Closed by noting the next step.",
            "Final note: we will reconvene.",
            "Ended with a quick recap of one item.",
        ],
        2: [
            "Recap: we covered three topics, decided on the staged rollout, and left one open question on staffing that I will resolve by Thursday.",
            "Wrap-up: agreed to pause feature X, committed to the new dashboard, and noted two follow-ups for next week.",
            "Closing summary: aligned on the priority order, decided next month's focus, and listed the three open items by owner.",
        ],
    },
}

FILLER_SENTENCES = [
    "The conversation lasted about thirty minutes.",
    "We met in a small room with the laptop set up between us.",
    "There were no interruptions.",
    "The tone was professional throughout.",
    "Notes were taken in real time.",
    "We started a few minutes after the hour.",
    "The setting was informal but focused.",
    "Background context had been shared in advance.",
    "Both parties had reviewed the latest data beforehand.",
    "There was a shared agenda visible on screen.",
]


def _generic_template(item_name: str, anchor: int) -> str:
    if anchor == 0:
        return f"Did not address {item_name.lower()}."
    if anchor == 1:
        return f"Touched on {item_name.lower()} briefly without specifics."
    return f"Demonstrated {item_name.lower()} with concrete examples and detail."


def _poisson_capped(rng: random.Random, lam: float, cap: int) -> int:
    # Knuth Poisson, then cap.
    L = math.exp(-lam)
    k = 0
    p = 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= L:
            break
    n = k - 1
    return min(n, cap)


def _anchor_for_skill(rng: random.Random, skill: float) -> int:
    """Higher skill biases toward 2; lower toward 0. ~15% chance of off-mode noise."""
    # Convert skill into a distribution over {0, 1, 2}.
    # skill=0 -> mostly 0; skill=0.5 -> mostly 1; skill=1 -> mostly 2.
    p0 = max(0.0, 1.0 - 2.0 * skill)
    p2 = max(0.0, 2.0 * skill - 1.0)
    p1 = max(0.0, 1.0 - p0 - p2)
    total = p0 + p1 + p2
    p0, p1, p2 = p0 / total, p1 / total, p2 / total
    r = rng.random()
    if r < p0:
        return 0
    if r < p0 + p1:
        return 1
    return 2


def _pick_template(rng: random.Random, item_id: str, item_name: str, anchor: int) -> str:
    options = ITEM_TEMPLATES.get(item_id, {}).get(anchor)
    if options:
        return rng.choice(options)
    return _generic_template(item_name, anchor)


def _length_target(rng: random.Random) -> int:
    r = rng.random()
    if r < 0.10:
        return rng.randint(15, 49)
    if r < 0.70:
        return rng.randint(200, 600)
    return rng.randint(600, 1500)


def _build_note_text(
    rng: random.Random,
    applicable_items: list,
    skill: float,
    target_length: int,
) -> str:
    sentences: list[str] = []
    for item in applicable_items:
        anchor = _anchor_for_skill(rng, skill)
        sentences.append(_pick_template(rng, item.id, item.name, anchor))

    rng.shuffle(sentences)
    text = " ".join(sentences)

    while len(text) < target_length:
        text += " " + rng.choice(FILLER_SENTENCES)
        if len(text) >= target_length:
            break
    return text[:target_length] if target_length < 50 else text


def generate_synthetic(
    authors: int,
    days: int,
    out_dir: str | Path,
    seed: int | None = None,
    end_date: datetime | None = None,
    rubric_path: str | Path = "data/rubric.json",
) -> Path:
    rng = random.Random(seed)
    rubric = load_rubric(rubric_path)
    event_types = rubric.event_types()
    if not event_types:
        raise ValueError("Rubric has no event types")
    # Non-uniform event-type weights (deterministic with seed).
    type_weights = [max(0.1, rng.random()) for _ in event_types]

    if end_date is None:
        end_date = datetime.now(UTC).replace(microsecond=0)
    elif end_date.tzinfo is None:
        end_date = end_date.replace(tzinfo=UTC)

    # Author profiles
    author_ids = [f"author_{i+1:03d}" for i in range(authors)]
    skills = {a: rng.uniform(0.2, 0.8) for a in author_ids}
    drifts = {a: rng.choice([-0.005, 0.0, 0.005]) for a in author_ids}

    notes: list[dict] = []
    for day_idx in range(days):
        day = end_date - timedelta(days=(days - 1 - day_idx))
        for author_id in author_ids:
            n_notes = _poisson_capped(rng, lam=0.7, cap=2)
            for _ in range(n_notes):
                event_type = rng.choices(event_types, weights=type_weights, k=1)[0]
                applicable = rubric.items_for_event_type(event_type)
                if not applicable:
                    continue
                effective_skill = max(0.0, min(1.0, skills[author_id] + drifts[author_id] * day_idx))
                target_len = _length_target(rng)
                text = _build_note_text(rng, applicable, effective_skill, target_len)
                occurred = day.replace(
                    hour=rng.randint(8, 17),
                    minute=rng.randint(0, 59),
                    second=rng.randint(0, 59),
                )
                notes.append(
                    Note(
                        note_id=f"n_{uuid.UUID(int=rng.getrandbits(128)).hex[:12]}",
                        author_id=author_id,
                        subject_id=f"subject_{rng.randint(1, max(1, authors * 2)):03d}",
                        event_type=event_type,
                        occurred_at=occurred,
                        text=text,
                    ).model_dump(mode="json")
                )

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    notes_path = out_path / "notes.json"
    notes_path.write_text(json.dumps(notes, indent=2, default=str))
    return notes_path


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="note_eval.ingestion")
    sub = parser.add_subparsers(dest="cmd", required=True)
    gen = sub.add_parser("generate", help="Generate synthetic notes")
    gen.add_argument("--authors", type=int, required=True)
    gen.add_argument("--days", type=int, required=True)
    gen.add_argument("--out", type=str, required=True)
    gen.add_argument("--seed", type=int, default=None)
    gen.add_argument("--rubric", type=str, default="data/rubric.json")

    args = parser.parse_args(argv)
    if args.cmd == "generate":
        path = generate_synthetic(
            authors=args.authors,
            days=args.days,
            out_dir=args.out,
            seed=args.seed,
            rubric_path=args.rubric,
        )
        print(f"wrote {path}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(_cli())
