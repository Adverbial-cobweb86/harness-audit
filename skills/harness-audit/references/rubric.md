# Scorecard

Score each dimension 0 to 5, with evidence (file, line count, token estimate, lint code). Total /40.
Thresholds are defaults; `.harness/config.json` budgets override them.

| # | Dimension | 5 looks like | 0 looks like | Evidence |
|---|---|---|---|---|
| 1 | Always-on size | each agent under budget (default ~5k est. tokens incl. skill listings) | tens of thousands of tokens before the first prompt | inventory, `/context`, H002 |
| 2 | Entry file quality | map under ~120 lines: why, what, how, routing table, gotchas | encyclopedia, history, pasted docs, generic advice | H001, reading |
| 3 | Single source of truth | AGENTS.md canonical, CLAUDE.md imports it, no repeated paragraphs, generated copies in sync | same content in CLAUDE.md, GEMINI.md, rules, vault and memory | H011, H012 |
| 4 | Progressive disclosure | scoped rules, skills for procedures, index with read_when | everything unscoped or @imported | H003, H004, H005 |
| 5 | Knowledge layer | docs/vault with frontmatter, generated index, log, placement folders, no orphans | scattered notes, no index, wikilinks only | H007 to H010, H017 |
| 6 | Sensors | hooks for post-edit and stop, pre-commit, CI, formatter/linters instead of prose style rules | only prose instructions | installed files |
| 7 | Cache stability | no dates/status/current work in always-on files | status boards in CLAUDE.md | H013 |
| 8 | Runtime health | startup context low, few compactions, sessions stay short and focused | frequent compaction, peak near window limit | transcripts, manual numbers |

Severity guide for findings: **error** blocks a healthy harness (truncation, broken generation, budget breach); **warn** wastes context or invites drift; **info** worth a look.

## Task benchmark (recommended)
Pick 3 to 5 real tasks that touch different areas (one bug fix, one small feature, one "where is X documented" question, one change that requires a decision record).
For each, before and after, in a fresh session of the same agent and model:
- success (yes/partial/no) judged by the user
- number of turns until done
- startup context and peak context (transcripts or UI)
- files read that were irrelevant (from the transcript)
- human corrections needed
Report medians. A restructure that shrinks context but lowers success is a regression.
