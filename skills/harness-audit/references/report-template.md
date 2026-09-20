# Report templates

Write in the user's language. Keep tables; keep prose short.

## Plan (`.harness/reports/plan.md`)

```
# Harness plan: <project> (<date>)
## Setup
Agents: ... | Obsidian: yes/no, topology ... | Knowledge root: ... | User-level files measured: yes/no
## Baseline
| Agent | Always-on est. tokens | Files | Biggest contributors |
Say which chars/token ratio produced these estimates and whether it is the 4.00 default or a
calibrated one, and call them a floor, never a measurement.
**If the always-on estimate for any agent exceeds the context window of the smallest model in
use, write it here as its own line and as a hard failure, not as a budget overrun: the
project does not open on that model at all — not for a trivial question, with no tools
loaded.** Name the model and both numbers.
Runtime (if available): median startup context, peak, compactions. Manual numbers.
## Scorecard
| Dimension | Score | Evidence |   (total /40)
## Proposed changes
### Low risk (approve as batch)
| # | Change | From | To | Saves (per agent) |
### Medium risk (approve per group)
### High risk (approve item by item)
## Not changing, and why
## Approvals
<filled with the user's decisions>
```

## Final report (`.harness/reports/HARNESS-REPORT.md`)

```
# Harness report: <project>
## Summary
3 to 5 sentences: what changed, measured effect, remaining risks.
## Before and after
<output of measure.py compare, including the chars/token line>
## Task benchmark
Environment proof (output of benchenv.py, before and after the battery): commit, ancestry,
entry-file line counts, docs directory, scoped rules, main tree clean.
| Task | Before (success, turns, peak ctx, tokens, tool uses) | After | Cost change | Verdict | Measured by |
`Measured by` is the process that produced the numbers: fresh session run by the user, local
script, or subagent. A good verdict with a cost well above the "before" is a warning, not an
approval — say so in the row.
If no task benchmark was run, say that plainly here instead of leaving the section out: the
static numbers say the harness got smaller, not that the agent still works.
## What moved where
| Content | Before | After |
## Maintenance layer installed
Hooks per agent, pre-commit, CI, keeper skill locations, budgets locked.
## Known gaps
Anything measured by a process that could not see the change, anything the user has not run
yet, and any lint code suppressed in `.harness/config.json` with the reason.
e.g. Antigravity hooks pending verification, external vault not covered by CI.
## How to keep it healthy
- Weekly or before release: /harness-audit check
- When lint reports H002/H006/H015: /harness-audit diagnose
```
