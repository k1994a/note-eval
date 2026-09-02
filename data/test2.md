# Coaching Chatbot — Design Decisions

Reference doc for implementation. Covers data stores, retrieval paths, orchestrator
routing rules, and model tiering.

---

## Data Stores

| Store | Contents | Role |
|---|---|---|
| SQL Server — coaching | Coaching sessions: notes, action items, follow-ups, metadata | Source of truth |
| SQL Server — metrics | Rep performance metrics | Queried via text-to-SQL |
| Azure AI Search | Coaching text synced from SQL, chunked with event-meaning annotations | Semantic retrieval only |

The vector index is a derived copy. SQL remains source of truth for coaching data.

---

## Retrieval Paths

The orchestrator routes every query to one of three paths.

### 1. Semantic coaching search → Azure AI Search

For questions where the target is unknown but the concept is known.

- Pre-filter on `attuid` + date range
- Vector search over the filtered set
- `k` set by the orchestrator based on scope

Example: *"Who did I talk to about improving discovery last month?"*

### 2. Scoped coaching fetch → parameterized SQL

For questions fully specified by metadata. No NL→SQL generation — this is a static
query with bound parameters.

```sql
SELECT session_date, notes, action_items
FROM coaching_sessions
WHERE attuid = @rep
  AND session_date >= @start
ORDER BY session_date;
```

Example: *"How did I coach Bob last month?"*

At ~30 sessions/rep/month, a rep-month fits in context whole. Return the full set
rather than retrieving.

### 3. Metrics → text-to-SQL

Open-ended aggregations against the metrics DB. This is the only path that needs
generated SQL.

---

## Non-Negotiables

**Pre-filter, never post-filter.** A single rep is well under 1% of the corpus. Post-filtering
ranks globally then drops non-matches, so a rep-scoped query can return near-nothing even
at high `k` — and it fails silently. Azure AI Search does filtered vector search natively;
use it.

**`k` is an orchestrator decision.** Narrow scope (single rep, short window) → high `k`,
effectively complete. Broad scope (team, org, cross-rep) → tight `k`, ranking matters.
Same index, same chunks, one knob.

**Order by session date.** Filter-only and high-`k` retrieval return in engine order.
Coaching narrative read out of chronological order degrades synthesis noticeably.

**State sample size.** Any thematic answer built from top-`k` must say "based on N sessions"
rather than implying it read everything. Response fluency is identical whether the sample
was representative or not — the user cannot tell. Coaching data drives manager decisions;
an unhedged prevalence claim is the failure mode that actually bites.

---

## Route to SQL, Not Vector

These fail on embeddings regardless of chunking or `k`:

- **Negation** — *"who haven't I coached on X."* Embeddings don't represent absence.
  Retrieve who *did*, then set-difference against the roster in SQL.
- **Prevalence counts** — *"how often did coaching cover discovery."* Top-`k` is a sample
  presented as a census.
- **Action item status** — open, overdue, closed, carried-forward. `"unclosed"` and
  `"closed"` sit close together in vector space. Use `status` / `due_date` / `owner` columns.
  The item text still lives in the chunk for grounding; only the status fields are queried
  relationally.

---

## Where Vector Search Earns Its Place

The pattern: **unknown target, known concept** — the filter itself is semantic and can't be
expressed as a column value.

- **Topic search without a keyword** — *"who did I talk to about improving discovery"*
- **Similarity to an exemplar** — *"find sessions like this one"* (query is a document)
- **Cross-rep pattern finding** — *"which reps are struggling with the same thing"*
  (no attuid filter; the semantic match is the scope)
- **Precedent lookup** — *"how have other managers coached someone weak on objection handling"*
- **Self-audit** — *"have I been coaching enough on pipeline hygiene"* (pair with an exact
  count for the quantitative half)

---

## Model Tiering

| Component | Tier | Rationale |
|---|---|---|
| Orchestrator / routing | Small | Classification + slot extraction. In front of every query — latency matters. |
| Query rewriter | Small | Coreference resolution and term expansion are mechanical. |
| Running summary | Mid | Lossy compression with no error correction. Not frontier work, but not the cheapest model either. |
| Synthesis / conversational agent | Frontier | Hardest job in the stack, and the only component the user sees. |
| Text-to-SQL (metrics) | Frontier | A wrong join is a wrong number delivered confidently. |

### Conversation state

Keep a **structured slot bag** — active rep(s), date range, current topic — updated
separately from the prose summary. Slots survive compression because they're overwritten,
not paraphrased. The prose summary then only carries conversational texture, where loss is
cheap.

Hold **6–8 turns verbatim** alongside the summary. Recent turns are where coreference
actually resolves, and raw text is cheaper than the summarization call needed to compress it.

---

## Deferred

Not building now. Revisit if the trigger condition appears.

| Item | Why deferred | Trigger to revisit |
|---|---|---|
| Extraction-at-write tagging (LLM pass at ingest → theme/category columns) | Overkill at ~30 sessions/rep/month with pre-filtering | Prevalence answers look unreliable in testing |
| Counting / tags table | Most counting questions are simple | Same as above |
| Index partitioning by rep or team | Premature at current volume | Index growth degrades filtered query latency |

---

## Watch in Testing

- **Multi-hop routing** — *"why did Sarah's close rate drop"* needs metrics *and* coaching,
  in order, with the second query shaped by the first. If the orchestrator must plan
  sequences rather than pick one lane, it may need a larger model.
- **Summary compression dropping filters** — an attuid set eight turns ago going missing is
  inherited silently by every downstream component.
- **Team-scope corpus size** — filter cardinality 1 → 15 moves the corpus from ~90 chunks to
  ~1,400. This is where tight `k` starts mattering. Know the `$top` ceiling before someone
  asks a question that returns thousands of chunks.
- **Small-model rewrite quality** — check for dropped filters or hallucinated constraints.
  Upgrade only if it stumbles.
