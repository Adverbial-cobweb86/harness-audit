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

**Who runs the tasks: the user, in a fresh session, on both sides.** Not the agent doing the
audit, and not a subagent of it. A subagent inherits the context snapshot its parent session
started with, so it measures the harness as it was at startup regardless of what is on disk
— which is why the "before" side happens to come out right (at that point the snapshot and
the disk agree) and the "after" side is worthless. The audit agent presents the prompts,
collects the numbers, and records which process produced each one.

### Choosing the tasks
Pick 3 to 5 real tasks that touch different areas (one bug fix, one small feature, one
"where is X documented" question, one change that requires a decision record).

**At least one task must come from outside the entry file's incident blocks** — from the
backlog, an open TODO, or a feature nobody has started. An incident block exists *because
somebody already found and fixed that trap*; the block is the record of the fix. A task
derived from it points, by construction, at code already in its final state. In the third
pilot 2 of 5 tasks were no-ops for exactly this reason. Write the pattern down where the
next person will read it: **the trap is documented because it was already repaired; look
for the trap, not for its repair.**

**Validate the design before running anything.** For each task, confirm the target state
does *not* exist yet: grep the symbol, check the column, open the file. It costs seconds and
it is what stops half the battery from being born useless. A no-op task still measures the
*choice* (which verification command, where the truth is read from) and that is worth
recording — but it does not measure executing under the rule, and if both sides run the same
prompt the comparison is empty on both sides and two identical no-ops look like a draw.

### Containing the tasks
**Every task runs in an isolated worktree, sandbox or disposable copy. No exceptions, not
even for tasks that only read.** "This task does not write" is a hypothesis about the
agent's behaviour, and the benchmark exists precisely because that hypothesis is not
reliable: in the third pilot a task classified read-only wrote a migration file straight
into the main tree. It did not break the policy — writing the file is not applying the SQL —
the containment design was simply wrong.

**Prove the environment before launching, and again afterwards:**
```bash
python3 .harness/scripts/benchenv.py --dir <worktree> --commit <audit commit> --main .
```
It resolves the directory's HEAD, asserts the audit commit is an ancestor of it, proves the
state by observable artefact (entry-file line counts, the docs directory, the scoped rules
on disk) and checks the main tree for stray writes. Exit 1 aborts; never launch "to see what
happens". A worktree is created from the default branch by default, not from the session's
HEAD — that one fact cost the third pilot ~2.17M tokens and produced five confident, false
verdicts. The output goes into the report next to the verdicts.

### What to record, per task, before and after
- success (yes/partial/no) judged by the user
- number of turns until done
- startup context and peak context (transcripts or UI)
- **tokens and tool uses**
- files read that were irrelevant (from the transcript)
- human corrections needed
- which process produced the measurement (fresh session, local script, subagent)

Report medians. A restructure that shrinks context but lowers success is a regression.

### Reading the cost, which is an instrument and not just an expense
An audit trades *guaranteed* context for *conditional* context. Afterwards a task can pass
two ways: the scoped rule fired at the right moment and the agent already had what it needed
(**cheaper**), or the rule did not fire and the agent hunted the answer down across the docs
(**dearer**). Both end in PASS. The verdict cannot tell them apart; the cost can.

So: **a good verdict with a cost well above the "before" is a warning, not an approval.** The
`read_when` on that block is written as a topic instead of a trigger, and it will fail the
day the agent has less patience for hunting. That is a correction of aim, not a rollback.

And the check does not depend on anyone remembering to look: `measure.py compare` exits 2
when a declared always-on reduction above 50% comes back with a median per-task cost change
below 10% (thresholds under `benchmark` in `.harness/config.json`). Those two numbers cannot
both be true, and in the pilot that pairing — 96.5% less always-on, costs at −2.4% and +1.6%
— was the environment being wrong, printed under a table and read as success twice.
