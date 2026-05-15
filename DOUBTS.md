# DOUBTS

Things I made a call on that you should manually verify or override before this is production. Listed in rough order of impact.

## 1. Rubric JSON schema

I defined a rubric schema with this shape:

```json
{
  "version": "1.0.0",
  "items": [
    {
      "id": "item_001",
      "name": "...",
      "description": "...",
      "applies_to_event_types": ["type_a", "type_b"],
      "anchors": {
        "0": "description of what a 0 looks like",
        "1": "...",
        "2": "..."
      }
    }
  ]
}
```

If your real rubric JSON has a different shape (nested categories, weights, dependencies between items, etc.), update `schemas/rubric.py` and `ingestion.py::load_rubric()`. Everything downstream consumes the Pydantic model, so you only need to fix parsing.

## 2. Event type taxonomy

I used generic placeholders (`type_a`, `type_b`, `type_c`). Replace with your real event types throughout `data/rubric.json` and the sample data generator. The pipeline does not hardcode event types anywhere — it reads them from the rubric.

## 3. Calibration target

I did not set a target agreement threshold for Agent 1 vs. ground truth. You said you need to build the ground-truth set. When you do, decide:

- Acceptable exact-match rate per rubric item (suggested floor: 70%).
- Acceptable within-±1 rate (suggested floor: 95%).
- What to do with items below threshold — tighten prompt? Tighten rubric anchors? Drop the item?

The calibration CLI computes both metrics; the threshold for action is yours.

## 4. Trend thresholds

`IMPROVEMENT_THRESHOLD = 0.3` and `WEAK_THRESHOLD = 1.0` in `aggregation.py` are guesses. With a 0/1/2 scale, 0.3 is a meaningful shift but not huge. Tune after you see real data.

Consider whether you want distributional thresholds (e.g., "% of notes scoring 2 increased by 15 percentage points") instead of mean-based. If notes are bimodal — lots of 0s and 2s, few 1s — mean shifts can hide real movement.

## 5. "Last 30 days" boundary

`last_30_days` is computed as `today - 30 days`, exclusive. If your reporting cadence is end-of-month or weekly, change `recent_window_start()` in `aggregation.py`.

## 6. Author volume floor

Authors with very few notes in a month will produce noisy trends. I did not set a minimum volume to suppress trend output. Decide:

- Hide trends when fewer than N notes in a month? Recommended: N = 5.
- Or always show, with a volume warning?

Current behavior: always show, with `note_count` available alongside every score in the output.

## 7. Insufficient-evidence rate threshold

Currently surfaced as a raw number per slice. No threshold for flagging. If insufficient-evidence rate exceeds, say, 30%, you probably want to alert that the slice isn't reliably scorable. Add to `aggregation.py` if useful.

## 8. Caching invalidation

Cache key includes rubric version. If you edit prompts in `src/note_eval/prompts/`, the cache will return stale results. Either:

- Include a prompt hash in the cache key (I did not do this).
- Manually clear `.cache/` after prompt changes.

I lean toward the prompt hash approach but didn't want to over-engineer. Decide.

## 9. Concurrency limit for parallel scoring

Agent 1 fans out aggressively. With hundreds of notes × dozens of rubric items, that's thousands of calls. The mock client handles this fine; the live OpenAI client will hit rate limits.

I set `MAX_CONCURRENT_LLM_CALLS = 10` in `llm.py`. Adjust based on your OpenAI tier and budget tolerance.

## 10. Error handling for malformed notes

Empty notes, notes with only whitespace, notes that fail rubric scoring entirely — I log and skip. They appear nowhere in output. If you want them counted as a separate category ("unscorable"), add to `agents/scorer.py`.

## 11. Schema for the final report

I designed an output JSON shape that I think is sensible. If your UI team wants different keys, nesting, or denormalization, change `schemas/report.py` — it's the only file that defines the contract.

## 12. Storage layer

`storage/repository.py` is a Protocol. The default implementation reads/writes JSON files. Your DB-backed implementation should satisfy the Protocol; nothing else needs to change. Test the contract by running the existing test suite against your implementation.

## 13. Author identity

I use opaque `author_id` strings. No PII anywhere. If your real data has names/emails, scrub at ingestion (`ingestion.py::ingest_notes`) before the data enters the pipeline.

## 14. Time zones

Notes have ISO 8601 datetimes; I assume UTC throughout. If your authors span time zones and "what month is this in" matters at the boundary, localize before aggregation.

## 15. Prompt drafts

The prompts in `src/note_eval/prompts/` are starting points, not final. They will need iteration on real data. Key things to watch:

- Scorer: does it over-use `insufficient_evidence` or under-use it?
- Monthly summarizer: does it invent patterns not in the evidence?
- Trend analyzer: does it narrate the table faithfully, or editorialize?
- Recent summarizer: are bullets actionable, or generic?
