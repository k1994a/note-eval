# Orchestrator v2 change request

Paste everything below the line into Copilot. Fill in the four model names in the tier table first.

---

Update the orchestrator setup. Apply these changes to .github/agents/orchestrator.agent.md, .github/skills/orchestrated-dev/SKILL.md and .github/skills/orchestrated-dev/plan-template.md. Keep all my existing edits; change only what's needed for the following.

1. Task size
Replace the current task-sizing rule. A task is one coherent slice of a feature that can be tested on its own, typically 300–500 changed lines across as many files as it needs. Split a task only when its parts can be tested separately or its Spec no longer fits on one screen. Never split just to keep tasks small.

2. Run tiers
Add this fixed menu. For every Implementer and Reviewer dispatch, the Orchestrator picks exactly one tier and passes that tier's model to the subagent. No other values are allowed.

| Tier | Effort | Context | Model to pass |
|---|---|---|---|
| light | low | standard | <exact model name> |
| standard | medium | standard | <exact model name> |
| deep | high | standard | <exact model name> |
| wide | medium | large (1M) | <exact model name> |

How to choose the Implementer tier:
- light: mechanical work such as wiring, config, renames, boilerplate, or tests that copy an existing pattern.
- standard: the default for normal feature work.
- deep: tricky logic, concurrency, algorithms, bugs with an unclear cause.
- wide: only when the task must read a large amount of code at once (cross-cutting refactor, very large files). A bigger context does not improve quality, so never pick wide for that reason.
The Reviewer runs at standard, or at deep when the Implementer ran at deep.
If a tier's model is unavailable, use the next lower tier and note it in the Run line.

3. Reviewer by risk
The Orchestrator decides for each task whether to run the Reviewer subagent.
- Always run it for: auth or permissions, data writes or migrations, concurrency, money, handling of untrusted input, changes to shared interfaces, and any fix round.
- Otherwise decide after the Implementer finishes, using git diff --stat, test results and the Implementer's notes. Run it if the diff is bigger than the Spec implied, touches unexpected files, or tests look thin, or if the Implementer noted deviations.
- Adding a review is always allowed. Skipping it on a task marked Risk: high requires a one-line reason in the Run line.

4. The Orchestrator always reviews
Whether or not the Reviewer runs, the Orchestrator reads the full task diff and writes the verdict for every task. If the Reviewer ran, use its findings as a checklist. This step is never skipped.

5. Escalation
Each fix round moves the Implementer up one tier (light → standard → deep). After 2 fix rounds, REDO or split the task as before.

6. Plan fields
Add these to each task in the plan template:
- **Risk:** high | low (set at planning; high means the Reviewer runs by default)
- **Run:** one line per round, for example "r1: impl=standard, reviewer=no. Why: config only, tests green, diff matches Spec"
The Orchestrator writes the Run line when it dispatches and adds the Reviewer decision after implementation.
