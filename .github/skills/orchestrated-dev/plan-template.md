# PLAN: <goal in one line>

<!-- Single source of truth. The Orchestrator owns everything except each task's
     "#### Implementer" block (Implementer) and "r<N> (reviewer)" entries (Reviewer).
     Keep it terse: fragments, file paths, SHAs. -->

- **Status:** planning <!-- planning | in-progress | done -->
- **Branch:** orch/<slug>
- **Start commit:** <sha>
- **Next step:** <one precise line: what the orchestrator does next>
- **Commands:** build `<cmd>` · test `<cmd>` · lint `<cmd>`

## Goal & acceptance criteria

- <what "done" means for the whole effort, as checkable statements>

## Architecture

<!-- 60 lines max. Components, data flow, key files, conventions and patterns to copy. -->

## Decisions

<!-- D1: <decision>. Why: <reason>. -->

## Tasks

### T1 — <title>

- **Status:** todo <!-- todo | in-progress | in-review | fix | done | blocked -->
- **Depends on:** none
- **Files:** `path/a`, `path/a.test`
- **Spec:** <exact change: files, signatures, pattern to follow>
- **Acceptance:** `<command>` passes; <observable behavior>
- **Base:** <sha> · **Head:** <sha, set on approval>

#### Implementer

- Done:
- Left:
- Notes:

#### Review

<!-- Append one entry per round:
- r1 (reviewer): CHANGES. checks: <cmd> pass
  - R1 [blocker] file:line. problem. fix.
- r1 (orchestrator): FIX. (1) ... (2) ... Rejected: R3 (reason).
-->

## Open questions & risks

-

## Session log

- <date> S1: <one line>
