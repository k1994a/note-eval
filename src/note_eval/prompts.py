"""Prompt templates used by the agents.

Each constant is a Python ``str`` with ``{placeholder}`` markers that callers
fill via ``str.format(**kwargs)``. Iterate on wording here; everything imports
from this module.
"""

SCORER = """\
You are an evaluator scoring a single note against a single rubric item.

Rubric item: {rubric_item_name}
Description: {rubric_item_description}

Scoring anchors:
- 0: {anchor_0}
- 1: {anchor_1}
- 2: {anchor_2}

Note text:
\"\"\"
{note_text}
\"\"\"

Score the note against this rubric item. Use these rules:

- Return 2 only if the note clearly meets the anchor for 2.
- Return 1 if partially present but shallow or lacking specifics.
- Return 0 if not addressed or addressed in a way that fails the anchor.
- Return "insufficient_evidence" if the note is too sparse, ambiguous, or off-topic to support any judgment on this item. Do not guess.

Return:
- score: 0, 1, 2, or "insufficient_evidence"
- evidence_span: a verbatim quote from the note that supports your score. Empty string if "insufficient_evidence".
- rationale: 1-2 sentences referencing the evidence.
- confidence: "high" if the evidence is unambiguous, "low" otherwise.
"""


MONTHLY = """\
You are summarizing one author's performance for one event type in one month.

Month: {month}
Event type: {event_type}
Number of notes this month: {note_count}

The following table shows scores for each rubric item this month:
{score_table}

For each rubric item, here are the evidence spans collected:
{evidence_by_item}

Produce:

1. For each rubric item, a 2-4 sentence qualitative summary describing what the author did well or poorly this month. Reference patterns across notes, not single quotes. Pick 2-3 representative evidence quotes from those provided.

2. A cross_item_themes paragraph (3-5 sentences) describing patterns that span multiple rubric items, if any.

Do not compute counts, means, or rates - those are already provided. Narrate them.
Do not invent evidence not present in the spans provided.
"""


TREND = """\
You are narrating month-over-month trends for one author and one event type.

The following table shows mean scores per rubric item per month:
{monthly_means_table}

Computed directions (improving / declining / flat / insufficient_data) per rubric item:
{directions}

Monthly summaries for context:
{monthly_summaries}

Produce:

1. For each rubric item, a single-line trend narrative. Reference the direction and one concrete reason from the monthly summaries if available.

2. An overall_summary: one line describing the author's overall trajectory across rubric items.

Faithfully narrate the computed directions. Do not editorialize or invent trends not supported by the means.
"""


RECENT = """\
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

Each bullet should reference a specific rubric item and be actionable, not generic. If you cannot find 2 in a category, say "No clear signal" for that slot - do not invent.
"""
