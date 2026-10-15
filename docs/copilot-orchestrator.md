# Copilot orchestrator setup

## What's in this folder

```
.github/
  agents/
    orchestrator.agent.md      # your strongest model: plans, dispatches, reviews diffs, writes verdicts
    implementer.agent.md       # cheap model: one task, small commits, notes in the plan
    reviewer.agent.md          # cheap or mid model: findings into the plan, never edits code
  skills/
    orchestrated-dev/
      SKILL.md                 # the protocol the orchestrator follows
      plan-template.md         # template for .orchestrator/PLAN.md
```

## Setup

1. Copy `.github/` into your repo root. If you already have a `.github/` folder, merge the two.
2. Edit the `model:` line in `implementer.agent.md` and `reviewer.agent.md` to use models your org enables.
   - Subagent models must be in the same cost tier as the orchestrator's model or below, or the subagent won't run.
   - If a subagent fails to start, the error message lists the models you can use.
3. In the VS Code Chat view, choose the **Local** harness, pick the **Orchestrator** agent, and select your strongest model.
4. Under **Configure Tools**, make sure **Run Subagent** is enabled.
5. Leave `chat.subagents.allowInvocationsFromSubagents` off. Only the orchestrator should start subagents.
6. Optional: turn on `chat.subagents.showCreditUsage` to see what each subagent run costs.
7. Optional: auto-approve the read-only and routine terminal commands (`git status`, `git diff`, `git log`, `git add`, `git commit`, and your test command). Otherwise you'll approve every one by hand.

## Use

- **Start:** with the Orchestrator agent selected, describe the goal. It writes `.orchestrator/PLAN.md`, shows you the task list, and waits for your go-ahead.
- **Resume:** open a new Orchestrator chat and type `resume`. Do this whenever a chat gets long; the plan holds all the state.
- **Read the plan:** `.orchestrator/PLAN.md` shows every task's status, the implementer's notes, the review findings, and the verdicts.

## Notes

- The plan is listed in `.git/info/exclude`, so it never shows up in commits or PRs. If you'd rather version it, remove that line and commit it separately.
- Each task gets its own `T<n>:` commits. To see one task's history, run `git log --oneline --grep '^T3:'`.
