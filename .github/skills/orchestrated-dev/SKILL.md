---
name: orchestrated-dev
description: Protocol for plan-driven orchestration. Break a coding goal into small tasks in .orchestrator/PLAN.md, delegate each to the Implementer subagent, have the Reviewer subagent check it, review the diff, and record status, notes and verdicts in the plan. Used by the Orchestrator agent to plan, run, and resume work.
argument-hint: A goal to build, or "resume"
disable-model-invocation: true
---

# Orchestrated development protocol

The plan file is the single source of truth. Chat history is disposable; any session must be able to resume from the plan plus `git log`.

## Roles

| Role | Model | Writes |
|---|---|---|
| Orchestrator | most capable | PLAN.md: everything except the blocks below. Never product code. |
| Implementer | cheap | Code and commits. Its task's `#### Implementer` block. |
| Reviewer | cheap or mid | Its `r<N> (reviewer)` entry under the task's `#### Review`. Never code. |

Task statuses: `todo` → `in-progress` → `in-review` → `done`, with `fix` (back to Implementer) and `blocked` (waiting on the user).

---

## 1. Start

If `.orchestrator/PLAN.md` exists and its Status is not `done`, go to **6. Resume**. Otherwise:

1. Run `git status --porcelain`. If the tree is dirty, ask the user what to do; never discard their changes.
2. If on the default branch, create a branch: `git switch -c orch/<short-slug>`.
3. Run `mkdir -p .orchestrator`, then add `.orchestrator/` to `.git/info/exclude` if it is not already there. This keeps the plan out of commits and diffs, so `git status --porcelain` stays empty when the code is clean.
4. Copy [plan-template.md](./plan-template.md) to `.orchestrator/PLAN.md`. Fill in Goal, Branch, Start commit (`git rev-parse --short HEAD`) and Commands.
5. Research only as much of the codebase as you need to write **Architecture** (at most 60 lines: components, data flow, key files, conventions to copy). Ask the user only about decisions you cannot infer.
6. Write the tasks (see 2).
7. Show the user the task list (id, title, one-line spec) and get a go-ahead before dispatching anything.
8. If planning took a lot of reading, tell the user to open a fresh Orchestrator chat and type `resume`. The plan holds everything.

## 2. Writing tasks

Size every task so a cheap model can finish it in one pass:

- One concern, at most 3–4 files, roughly 150 changed lines or fewer.
- The Spec names the exact files, function signatures or interfaces, and a pattern to copy ("follow `src/handlers/user.ts`").
- Acceptance lists the commands that must pass and the observable behavior. Tests go in the same task as the code they test.
- Order tasks so the build and tests stay green after each one. Fill in **Depends on**.

Bad: "Implement config loading." Good: "Add `loadConfig(path): Config` in `src/config.ts` that reads YAML, applies defaults from `DEFAULTS`, and throws `ConfigError` on invalid keys. Tests in `src/config.test.ts`."

## 3. Dispatch Implementer

Before dispatching:
- Set Status to `in-progress`.
- On the first round only, set **Base** to `git rev-parse --short HEAD`. Fix rounds keep the same Base.

Prompt (keep it this short; anything longer belongs in the plan, where it survives):

~~~
Task T<n>, round r<N>. Plan: .orchestrator/PLAN.md
Read "## Architecture" and "### T<n>", then implement per your instructions.
[Fix rounds only] Fix every numbered item in "r<N-1> (orchestrator)" under T<n> > Review.
[Optional] <1–3 lines of context that are not in the plan>
~~~

When it returns:
- `git status --porcelain` must print nothing.
- Every commit in `git log --oneline <Base>..HEAD` must start with `T<n>:`.
- If either check fails, or Implementer reports PARTIAL, re-dispatch with one line saying what is wrong.
- If BLOCKED: read the question in the task's Implementer block. Answer it in the Spec (ask the user if it is a product decision), then re-dispatch.
- Set Status to `in-review`.

## 4. Review

### 4a. Reviewer

~~~
Review task T<n>, round r<N>. Plan: .orchestrator/PLAN.md
Range: <Base>..HEAD
Add your "r<N> (reviewer)" entry under T<n> > Review, per your instructions.
~~~

Afterward, `git status --porcelain` must still print nothing. Reviewer must not change code.

### 4b. Your own review

1. Run `git diff --stat <Base>..HEAD`. Changes to unexpected files are out of scope and mean FIX.
2. Run `git diff <Base>..HEAD -- <files>`. Skip lockfiles and generated files.
3. Go through each reviewer finding and decide: agree, or reject (with a reason of a few words).
4. Look for what a narrow-context reviewer misses: Spec and Acceptance fully met; fits Architecture and Decisions; consistent with earlier tasks; no duplicated helpers; tests actually exercise the behavior.
5. Run the Acceptance commands yourself if anyone reported a failure, or if you doubt the result.

### 4c. Verdict

Append one line under the task's `#### Review`:

~~~
- r1 (orchestrator): FIX. (1) Return defaults on empty file, src/config.ts:42 [R1]. (2) Add missing-file test [R2]. Rejected: R3 (style only).
~~~

- **APPROVE:** Set Status to `done` and **Head** to `git rev-parse --short HEAD`. Collapse the task's Review block to one line (`r1–r2 reviewed; APPROVE`) plus any deferred minors. Update **Next step**. Add to Decisions or Architecture anything that changed.
- **FIX:** Set Status to `fix`. Write a numbered must-fix list; only these items get fixed, so leave out nits. Allow at most 2 fix rounds; after that, REDO or split the task.
- **REDO:** Run `git revert --no-edit <Base>..HEAD`. Rewrite the Spec with what went wrong, set Status to `todo`, and clear Base.
- **BLOCKED:** The task needs a user decision. Ask the user, set Status to `blocked`, and add the question to Open questions.

Deferred minors go in the task's `Left:` line or become a new task.

## 5. Finish

1. When every task is `done`, dispatch Reviewer on the whole branch (range `<Start commit>..HEAD`) and ask it to look for cross-task issues only. Turn real issues into new tasks.
2. Set Status to `done` and append to the Session log.
3. Report to the user: what was built, the commit range, and deferred items.

Do not push or open a PR unless the user asks.

## 6. Resume

1. Read PLAN.md fully.
2. Run `git status --porcelain` and `git log --oneline <Start commit>..HEAD`.
3. Reconcile the plan with git:
   - A task marked `in-progress` with `T<n>:` commits after its Base is really `in-review`.
   - Uncommitted changes: ask the user; never discard them.
4. Append a line to the Session log and continue from **Next step**.

## 7. Context budget

- The plan is the memory, so after a task is approved, do not re-read its diff.
- Keep plan entries terse: fragments, file paths and SHAs, not prose.
- When the chat is long, finish the current task, make **Next step** precise, and tell the user: "Open a new Orchestrator chat and type `resume`."
