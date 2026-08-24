# Incremental LLM Summarization over Recurring Conversations

A design write-up for a system that produces rolling 30-day summaries of recurring
1:1 coaching conversations between a manager and a direct report. Conversations
cover performance metrics, tactics, follow-ups, commitments, and adherence to a
sales playbook.

The same pattern applies to any domain with a stream of timestamped, text-heavy
events per entity: case notes, incident reviews, customer interactions, standups.

---

## Problem

- Each entity (a coach) has **N conversation events** over time, each keyed by UUID.
- A summary is requested for a **rolling 30-day window**, on demand.
- Between requests, new events arrive. Old events do not change.
- Summaries must be **consistent** — the same inputs should produce the same
  narrative, and numbers must never be invented.
- Latency matters, because the summary is generated in response to a user action.

---

## Architecture as built

Three stages, with a persisted intermediate layer.

```
raw event text
      │
      ▼
┌─────────────────────┐
│  Insights agent     │  batched extraction over chunked events
│  (per event)        │  → topics, quotes, commitments, action items
└─────────────────────┘
      │
      ▼
┌─────────────────────┐
│  Deterministic      │  metric deltas computed in code, not by the model
│  metric pass        │
└─────────────────────┘
      │
      ▼
┌─────────────────────┐
│  SQL: one row       │  the cache. keyed by event.
│  per event          │
└─────────────────────┘
      │
      ├──────────────┐
      ▼              ▼
┌───────────┐  ┌───────────┐
│ Paragraph │  │ Deep dive │   reduce step over N insight rows
│  summary  │  │  / HTML   │
└───────────┘  └───────────┘
```

At request time: load cached insight rows for the window, extract insights for any
events not yet cached, then reduce the combined set into a paragraph or a deep-dive
report.

**Worked example.** A coach has 10 events in the window. 5 already have rows in SQL;
5 are new. The 5 new ones go through the insights agent and are written to SQL. All
10 insight JSONs are then passed to the reduce step, which emits the paragraph or
the deep dive.

---

## Assessment

**This is the right shape.** It is incremental map-reduce with a materialized
intermediate layer — the standard pattern for production summarization, and the
same approach behind most commercial "summarize my data" assistants. The specific
things it gets right:

| Decision | Why it holds up |
| --- | --- |
| Expensive extraction cached, cheap reduce at request time | Cost is paid once per event, not once per request |
| One row per event | Any window is a query, not a re-run |
| Metrics computed deterministically outside the model | Removes the single largest source of summary errors |
| Validation between extraction and reduce | Catches structural failures before they reach the user |
| Lazy caching instead of a scheduled job | Correct for an unproven tool — see below |

**Grade: B+.** The extraction path is well-guarded. The reduce path is not — it is
currently the least defended stage and the one most likely to produce output that
looks fine and is subtly wrong.

---

## Caching strategy: lazy, not scheduled

A nightly batch job would guarantee warm caches, but it is the wrong first move for
a tool with no proven adoption. It requires infrastructure that may be discarded,
and it does work for entities nobody asks about.

Lazy caching reaches the same steady state without the infrastructure. The first
request for a given coach is slow; every subsequent one rides the cache. Adoption
data comes for free — rows written per coach, request frequency, and repeat usage
are all visible in the cache table itself.

**Size the worst case explicitly:** slowest single-event extraction × maximum events
in a 30-day window, with a cold cache. If that number is tolerable, stop optimizing.
If it is not, the fixes are all in-process:

- **Fan out extraction concurrently.** Sequential extraction of 10 events costs 10×
  one event. Concurrent extraction costs roughly 1×. This alone usually resolves the
  worst case.
- **Write each insight row as it completes,** so a timeout partway through does not
  discard completed work.
- **Stream or show progress.** A 20-second first run that displays activity is
  tolerable; the same 20 seconds behind a spinner is not.
- **Extract inline at write time if you control the ingest path.** This is not a
  scheduled job — it is just doing the work when the data arrives, which yields a
  warm cache with no scheduler.

---

## Consistency levers

Ordered roughly by impact:

1. **Keep all numbers out of the model.** Metric deltas, counts, and trends should be
   computed in code from structured data. Already done here; it is the highest-value
   decision in the system.
2. **Pin the model version and set temperature to 0.** "Latest" aliases silently
   change behavior underneath you.
3. **Enforce a strict output schema** via structured output or tool-calling, not by
   asking for JSON in the prompt.
4. **Store `prompt_version` and `model_version` on every cached row.** This makes
   staleness detectable and lets you re-run only affected rows after a prompt change,
   instead of invalidating the entire cache.
5. **Have the reduce step cite event IDs,** so any claim in a summary is traceable
   back to a specific conversation.

---

## Chunking and event identity

Extraction is batched: multiple events are packed into one call, with chunk size
governed by a token count.

**The hazard.** If chunk boundaries are computed from a continuous token stream, then
adding a single new event can reshuffle which events land in which chunk. The same
event then gets summarized differently depending on what it was batched alongside.
This is a structural consistency failure, not a model failure, and no amount of
temperature tuning fixes it.

**Recommendations:**

- **Never split mid-event.** One event is the atomic unit; only whole events get
  packed into a chunk.
- **Freeze chunks once full.** New events start a new chunk rather than being appended
  to the last partial one.
- **Content-address the cache key:** hash of the ordered event IDs in the chunk, plus
  prompt version and model version. Identical input set → cache hit. Anything else →
  a new row, never a silent overwrite.
- **Handle the oversized single event explicitly.** An event that exceeds the chunk
  budget on its own should be split internally and flagged, not silently truncated.

### Tokenizer mismatch

If token counts are produced by a tokenizer belonging to a different model family
than the one performing extraction, the counts will not match the real budget. Treat
them as an estimate and leave meaningful headroom under the context limit rather than
packing to the line. Use the provider's own token-counting endpoint where available.

### Event labels in prompts

The extraction call needs to return output keyed per event so results can be split
back into rows. Three options:

| Approach | Problem |
| --- | --- |
| Positional index (`0, 1, 2`) | Nothing binds the index to content. A wrong index still validates. |
| Full UUID | 36 random characters. Models transpose and drop digits; failures are transcription noise, not real errors. |
| **Short alias (recommended)** | — |

Bind a short alias in the prompt and keep the mapping in code for the duration of the
call:

```
[E1] (2026-07-03) <conversation text>
[E2] (2026-07-11) <conversation text>
```

The model returns `E1`, `E2`; code maps back via `{E1: uuid, E2: uuid}`. Short enough
to emit reliably, hard to hallucinate plausibly, and a mismatch is immediately
obvious. Including the date gives the model a second grounding handle that also
serves as a sanity check on the output.

Because the reduce step always operates on per-event rows, aliases only need to be
stable **within a single extraction call**. They can be regenerated fresh every time.
No cross-call identity scheme is required.

---

## Validation policy

Extraction returns one object per input event. Define explicit handling for each
failure mode and log which one fired:

| Failure | Handling |
| --- | --- |
| **Missing event** — 4 objects returned for 5 inputs | Retry the chunk. Do not accept a partial write. |
| **Hallucinated ID** — an identifier not in the input set | Reject the entire chunk response. This usually indicates the model lost track, so remaining entries are also suspect. |
| **Duplicate** — same event twice, often with conflicting content | Same as above. |

Log failures keyed by chunk size. This gives an empirical ceiling on batch size: if
validation failures climb sharply past a certain number of events per chunk, that is
the limit, and it is cheaper to read it off logs than to guess.

---

## The reduce step: dilution, not overflow

At a realistic maximum of ~30 events per 30-day window, compacted insight JSONs are
nowhere near a modern context limit. **Overflow is not the risk.** Dilution is, and it
is worse because it raises no error.

Given 30 undifferentiated objects, a model produces a fluent paragraph that
disproportionately weights the earliest and most recent events and flattens the middle
of the window into generic filler. Nothing fails. The output simply misrepresents what
happened in week two, in prose confident enough that nobody checks.

**Mitigations, in order of effort:**

- **Give the reduce step structure instead of a pile.** Sort insights chronologically,
  group them by week, and require output anchored to those buckets — "week of X: these
  commitments, these metric movements." A model asked to cover four labeled buckets
  covers four buckets.
- **Slim the payload per path.** A paragraph summary likely does not need every quote
  from every event. Drop the quotes array for the paragraph path and retain it for the
  deep dive. Less content to dilute.
- **Add a mid-tier only if needed.** Weekly rollups that the monthly summary consumes,
  themselves cached. At ~30 events this is probably premature; build it only if the
  structured-prompt fix demonstrably fails.

**The test that settles this:** run the reduce step against a real maximum-volume
window and check whether the middle of the month appears in the output at all. That is
a same-day experiment, and it determines whether any further architecture is warranted.

---

## Open questions

These were not resolved and each one materially affects the design:

1. **Does the deep dive re-read raw conversation text, or only the cached insight
   JSONs?** If it re-reads raw text, there is a second expensive path that the cache
   does not cover — and it, not extraction, is the real latency risk.
2. **Can the paragraph summary and the deep dive contradict each other?** Same inputs,
   two independent generations, two narratives. If one reports improvement on a metric
   and the other implies otherwise, that is the trust-killing bug, and it rarely
   surfaces in testing because the two outputs are typically reviewed separately.
   Consider deriving both from a single shared intermediate, or asserting agreement on
   the deterministic metric fields.
3. **What happens when an event has little usable content?** A short conversation that
   is mostly scheduling still gets a schema with `commitments` and `action_items`
   fields to fill. Schema-filling pressure on thin inputs is the most common source of
   fabricated obligations in this architecture. The extractor must be permitted — and
   explicitly instructed — to return empty arrays. **Check this before anything else:**
   the visible failure is a person being held to a commitment they never made.

---

## Summary of recommendations

**Do now**

- Verify the extractor returns empty arrays on thin events rather than inventing content
- Fan out new-event extraction concurrently; write rows as they complete
- Test the reduce step against a maximum-volume window and check mid-window coverage
- Structure the reduce prompt into chronological buckets

**Do soon**

- Add `prompt_version` and `model_version` to every cached row
- Switch to short aliases for per-event output keying
- Content-address chunk cache keys by ordered event IDs
- Define and log the three validation failure modes

**Defer until justified by data**

- Scheduled batch extraction
- Weekly mid-tier rollups
- Any further architectural change to the reduce path