# Report templates

Write in the user's language. Keep tables; keep prose short.

## Plan (`.harness/reports/plan.md`)

```
# Harness plan: <project> (<date>)
## Setup
Agents: ... | Obsidian: yes/no, topology ... | Knowledge root: ... | User-level files measured: yes/no
## Baseline
| Agent | Always-on est. tokens | Files | Biggest contributors |
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
<output of measure.py compare>
## Task benchmark
| Task | Before (success, turns, peak ctx) | After | Verdict |
## What moved where
| Content | Before | After |
## Maintenance layer installed
Hooks per agent, pre-commit, CI, keeper skill locations, budgets locked.
## Known gaps
e.g. Antigravity hooks pending verification, external vault not covered by CI.
## How to keep it healthy
- Weekly or before release: /harness-audit check
- When lint reports H002/H006/H015: /harness-audit diagnose
```
