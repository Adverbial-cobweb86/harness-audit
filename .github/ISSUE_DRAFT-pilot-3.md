# Always-on can grow past the model's context window; the verify promises a measurement it cannot take

Findings from a third pilot, run on a private project (Tavoloo) on 2026-09-20 with skill
version 1.4.0. The project's entry file was a `CLAUDE.md` of 6,198 lines and 589 KB, with an
`AGENTS.md` of 1,754 lines that Codex was reading at 19%. The audit brought startup context
from 347.2k to 70.5k tokens and memory files from 285.8k to 9.3k, and Codex back to 100%
read coverage. The behavioural half of the "after" benchmark was invalidated, and that is
where the sharpest findings come from.

No product data from the pilot project is included. Numbers below are measurements unless
they say otherwise.

---

**F4 — the always-on grew to the point where no 200k-window model could open the project at
all.** Not "over budget": a hard failure. Before the restructure the `CLAUDE.md` alone was
worth about 279,000 tokens (603,471 bytes at the ratio measured in F1), which exceeds a
200,000-token window before any system prompt, tool definition or question is added. There is
no session to be had, not even for a trivial question with no tools loaded. `H002` compares
the estimate against a fixed budget of 5,000 tokens and has no way to say this; the two
failures are different in kind, and this one is the more actionable. The fix is to compare
the always-on against the context window of the smallest model the user intends to use, and
to say so in those words. (An earlier version of this finding cited a subagent probe
returning `~285,549 tokens (limit 200,000)` as independent confirmation. That evidence was
wrong and is withdrawn: the number is the subagent's whole request, which the error message
itself decomposes into 172,299 tokens of the parent conversation plus system prompt and tool
definitions. Rerun after the restructure it barely moved, because what dominated it was never
the harness. Two numbers 0.09% apart looked like confirmation and were not. The conclusion
above stands on the other path.)

**F12 — a subagent inherits its parent session's *starting* context snapshot, so it cannot
measure a harness that changed afterwards.** Probe: a clean worktree at the audit commit, and
two questions to a subagent — what is in the `CLAUDE.md` of *your context*, and what is in
the `CLAUDE.md` *on disk here*. Context: the old file, log present, first line
`# CLAUDE.md — Tavoloo (estado do projeto)`. Disk: 30 lines, 7 scoped rules, a `docs/` tree.
The disk had the new harness; the subagent's context had the one loaded at the parent's
startup. This is not fixable by choosing a better worktree: the inheritance is upstream of
where the files are. The only valid instrument is a genuinely new session. Consequence for
this skill: **`SKILL.md` verify step 4 orders a measurement the agent cannot produce.** Step 1
says "Ask the user to open a fresh session"; step 4 says "rerun them in fresh sessions and
record success, turns and context" in the imperative, addressed to the agent — and that is
the one that gets followed. `references/rubric.md` has the same gap: "in a fresh session of
the same agent and model" never names who opens it. Following step 4 cost 2.17M tokens and
produced five confident, false verdicts with the appearance of method. The correction:
`verify` measures alone what it can measure alone (`/context` via the number the user pastes,
lint, budgets, ratchet, entry-file sizes, Codex read coverage), presents the benchmark
prompts, asks the person to run them in a fresh session, and states in one sentence why it
cannot do it itself. The report should record which process produced each measurement.
(A correction to a premise: this skill has no README, in any language — the ambiguity is in
`SKILL.md` and `rubric.md`, and pointing at a README makes the finding unactionable.)

---

### F11 — the benchmark never proves which commit the environment is on

The five "after" tasks ran in isolated worktrees. A worktree is created from the default
branch, not from the session's HEAD, so all five ran against the *old* harness: 6,198-line
`CLAUDE.md`, no `docs/`, no scoped rules. ~2.17M tokens, no valid measurement. Worse than the
waste: results were written from it. Tasks were recorded as PASS on the grounds that "the
scoped rule fired" when no rule existed in that tree, and the agents were blamed for
misattributing a source when their attribution was right. An unverified environment does not
just produce a useless number, it produces a confident and false one.

Two commands would have caught it before launch:

```
git worktree list
git merge-base --is-ancestor <audit commit> <worktree HEAD>
```

Suggested: before launching any task, resolve the commit of each environment, assert the
change is an ancestor of it, prove the state by observable artefact (entry-file line counts,
existence of the docs directory, the list of scoped rules) and **abort** if any of it fails.
Repeat the proof after the battery — an environment can change in the middle. The proof
belongs in the report next to the verdicts.

### F10 — per-task cost is an instrument, and the signal was printed and not read

An audit trades guaranteed context for conditional context. Afterwards a task can pass two
ways: the scoped rule fired at the right moment and the agent already had what it needed
(cheaper), or it did not fire and the agent hunted the answer across the docs (dearer). Both
end in PASS. The verdict cannot distinguish them; the cost can. In this project the log moved
out of the prompt was 433 KB, so one reading of it doubles a task's cost — the signal is
coarse, not subtle.

The rubric asks for success, turns, startup and peak context, irrelevant files read and human
corrections. It does not ask for **tokens and tool uses per task**, and that is the number
carrying the signal.

It also failed as an instrument in a way worth reporting: the finding was written, and two
commits later not applied. Tasks T3 and T4 came back at −2.4% and +1.6% against an always-on
96.5% smaller. That cannot hold, and it was exactly the symptom F11 describes. "Cost reading"
was written under each table and the conclusion was not drawn, twice. The lesson is about the
shape of the instrument, not about discipline: **a signal that depends on somebody remembering
to look at it is not ready.** The comparison should be automatic and should fail loudly — for
example, a declared always-on reduction above 50% together with a median per-task cost change
below 10% aborts the battery and sends the operator to check the environment, instead of
printing a table that reads as success.

### F1 — the token estimator is off by 1.90x on dense technical markdown

`scripts/hlib.py` estimates `len(text) / 4`.

| | |
|---|---|
| Memory files loaded | 600,892 characters · 618,740 bytes |
| `/context`, Claude Code, fresh session | 285,800 tokens |
| **Measured** | **2.10 chars/token** |
| Assumed | 4.00 chars/token |
| **Error** | **1.90x, always downwards** |
| `CLAUDE.md` estimated | 146,498 tokens |
| `CLAUDE.md` actual | **278,713 tokens** |

**The cause is not the language.** The bytes-per-character ratio of these files is 1.030, so
accents and emoji account for ~3% of the bytes and cannot explain a 1.9x error. 4.00 is the
figure for running English prose. This content is not prose: markdown tables, bold markers,
blockquotes on every line, backticked identifiers (`reservation_max_horizon_days`,
`x-vercel-ip-country`), UUIDs, deploy hashes. Punctuation and identifiers fragment far more
than words. Anyone who implements this as "×1.9 for Portuguese repositories" will underestimate
a technical repository in English by the same margin.

The ratio was validated independently after the restructure: 86,670 tokens projected from the
remaining 182,008 characters at the same 2.10; a fresh-session `/context` measured 86,800.
**0.1% error**, on a file set 69.7% smaller than the one the ratio was derived from.

Why it matters: `H002` compares the estimate against a 5,000-token budget. Underestimating by
1.9x means a harness twice over budget reads as inside it, and one at the threshold passes.

Suggested: calibrate from a real measurement when one exists (`--manual` already carries
`/context`), report which ratio was used, and never present the static estimate as a
measurement — at minimum call it a floor and say the real number is usually higher on
technical markdown.

### F5 — benchmark tasks drawn from incident blocks land on work already done

`references/rubric.md` asks for 3 to 5 real tasks across different areas but does not say
where to take them from. The natural source during a `diagnose` is the entry file's incident
blocks: that is where the documented traps are, with the failure mode already described.

**Measured: 2 of 5 tasks were no-ops.** One targeted a component that already had the
translation helper the task asked for; the other targeted a field already captured in the
live function definition.

The cause is structural: **an incident block exists because somebody already found and fixed
that trap.** The block is the record of the fix, so a task derived from it points, by
construction, at code already in its final state. A no-op task still measures the *choice*
(which verification command, where the truth is read from), which is worth recording, but it
does not measure executing under the rule — and if both sides run the same prompt, the
comparison is empty on both sides and two identical no-ops look like a draw.

Suggested: require at least one task from outside the incident blocks (backlog, an open TODO,
an unstarted feature); add a design-validation step confirming the target state does not exist
yet (grep the symbol, check the column) before running; and write the pattern down — *the trap
is documented because it was already repaired; look for the trap, not for its repair*.

### F6 — every benchmark task needs isolation, including the ones that look read-only

Only tasks predicted to edit files were isolated in a worktree. One classified as read-only
("it stops before the SQL") wrote a migration file straight into the project's main tree. The
agent did not break the policy — writing the migration file is not applying the SQL, and it
did stop before executing. The containment design was wrong: "does not apply" was confused
with "does not write".

"This task does not write" is a hypothesis about the agent's behaviour, and the benchmark
exists precisely because that hypothesis is not reliable. Suggested: require isolation by
construction (worktree, sandbox or disposable copy) for every task, and check the main tree's
`git status` after *each* task rather than at the end of the battery — that is how the leak
surfaced, and it surfaced by accident.

### F3 — `H011` describes a divergent fork as content paid twice

`H011` reported 41 identical paragraphs between `CLAUDE.md` and `AGENTS.md` as "paid twice".
Nobody pays twice here: Claude Code reads only `CLAUDE.md` (there is no `@AGENTS.md` import)
and Codex reads only the first 32 KB of `AGENTS.md`.

The real problem is worse. The two files are a divergent fork: `AGENTS.md` stamped
2026-07-03, `CLAUDE.md` stamped 2026-09-10 — two months and 4,444 lines apart. Codex was
operating on July's truth, truncated to 19%, with no signal of either.

Suggested: when `H011` fires, compare the two files' sizes as well. If they diverge
materially, emit a distinct code saying so and naming which agent reads which file, instead
of talking about double payment and sending the reader to look for a duplication that is not
the problem.

### F2 — `detect.py` reported no project folder for a vault that has one

`folders_named_like_project` returned `[]` for the user's Obsidian vault. The folder exists:
`B01 Projetos/tavoloo/`, with an overview, 204 lines of decisions and 361 of log, found by
hand with one `ls`. The folder name (`tavoloo`) is a substring of the project directory name
(`tavoloo-fmsolutions-main`), not equal to it, and the matching requires equality.

Impact: the diagnose nearly concluded there was no knowledge layer at all, when the
destination for the content already existed and was already the documented workflow in the
user's own `~/.claude/CLAUDE.md`. A plan generated from that `[]` would have proposed building
what was already there.

Suggested: match on tokens (split the project name on `-`/`_`, match folders against any token
of 4 characters or more), and always list the vault's top-level folders so a human can settle
it — an empty match list is not an answer, it is the absence of one.

### F8 — `H017` treats application syntax as a broken wikilink

Five `info` findings in `docs/architecture/`:

```
[INFO] H017 docs/architecture/edge-functions.md: wikilink [[PRODUCT:<uuid>]] does not resolve to a file
```

These are false positives. `[[PRODUCT:<uuid>|name]]` is that project's product-link marker:
an edge function emits the token and the frontend turns it into a clickable link. The
documentation has to quote the syntax exactly as it is, and following the suggested fix
("prefer a markdown link with a relative path") would corrupt the documentation of a live
protocol.

Suggested: ignore wikilinks whose target contains `:` or a placeholder such as `<uuid>` — the
signature of machine syntax rather than a note reference — and/or accept a list of suppressed
patterns in `.harness/config.json`, which is the minimum for a lint to coexist with
documentation that quotes code. Severity `info` is right: as `error` it would have blocked a
commit for documenting the truth.

### F7 — the freshly installed pre-commit blocked the restructure it exists to enforce

Immediately after `install.py --apply`, the first migration commit was refused: `H001` flagged
both entry files as over the 120-line budget. Correct — they were. But closing them *is* the
next step of the approved plan, and the gate has no "migration in progress" state, so it
blocked exactly the work it exists to demand. `--no-verify` was used once, with the reason
written into the commit message. Recorded because a silent bypass is how a quality gate stops
existing.

Suggested: have `install.py` record a baseline of the errors present at install time and have
the pre-commit fail only on *new* ones; or a short-lived `.harness/MIGRATION` marker, created
by `apply`, that degrades `error` to `warn` and disappears at `verify`; or at minimum, a
warning at the end of `install.py` that the gate will block until the plan is closed.

### F9 — a command guard that blocks whoever writes *about* the command

**Not a finding about this skill.** The guard in question was written inside the pilot
project, not installed by the skill, and the skill ships no command matcher at all. It is
reported here because the trap is generic and any command guard will hit it — read it as a
requirement to put on guards that an audit plan proposes, not as a defect to look for in this
repository's code.

A `PreToolUse` hook refused three commands that had broken production. It matched the pattern
against the whole command text. The first commit attempted was refused by the hook itself,
because the commit message *explained the rule* and therefore contained the forbidden string.
There was then no way out through Bash: every command written to fix the guard also quoted the
string, and was blocked too. The escape was an editor tool, which does not go through the
Bash matcher.

Worse, and only visible at the end of the audit: **the blocked call is aborted whole.** The
refused Bash call also carried the creation of a shell script and an edit to `AGENTS.md`.
Nothing ran. The guard was rewritten, the commit redone, and the script was treated as
existing for three turns — including being listed as a merge blocker. It did not exist.

Requirements this suggests: strip heredocs and quoted content before matching, so the matcher
matches the command and not the string anywhere in the text; keep a test case asserting that
`git commit -m "never use <forbidden command>"` **passes**; and after any block, check what of
the call actually happened rather than assuming only the offending part was lost. This applies
equally to pre-commit hooks, agent hooks and shell lint.

### F13 — merging a pre-audit branch undoes the audit and no gate fails

Observed on another pilot repository and confirmed here: merging a branch older than the audit
restores the pre-audit entry files, and the whole battery passes — typecheck, build, tests and
the harness lint. Nothing flags it.

Structural reason: every gate measures **the state that arrived**, not the distance from the
last known measurement. The only gate with memory is the `H015` ratchet, and it keeps that
memory **inside the tree it audits**:

```python
lock_path = root / ".harness/budgets.lock.json"
lock = json.loads(read_text(lock_path)) if lock_path.exists() else {}
...
if cfg.get("ratchet") and locked and tok > locked * 1.05:
```

`tok` comes from disk; `locked` comes from a versioned file. A merge brings both, mutually
consistent: small entry file again, small lock again, comparison false. **The baseline travels
with the change it was supposed to block.** A gate whose reference sits in the same commit it
audits is not a gate.

There are two distinct cases here, and whoever implements a fix will tend to see only the
first:

| Case | What happens | Why it deceives |
|---|---|---|
| Lock **stale** (arrived with the merge) | The condition is evaluated and comes out false, because `tok` and `locked` regressed together | A comparison *happens*, it just uses a contaminated reference |
| Lock **absent** (branch older than the lock) | The condition is **never evaluated** — `locked is None` short-circuits the `and` | There is no comparison at all. The gate switches itself off |

The absent case is worse on three counts: nothing is read, so there is nothing to inspect
afterwards; the `else {}` turns "I cannot measure" into "passed", which is the wrong trade in a
gate; and it is the state of every branch older than the audit — that is, the most likely
regressive merge is exactly the one the ratchet does not look at.

Open question, with no proposal attached: can the gate detect regression against the last known
measurement rather than only measuring the current state? That requires the reference to live
**outside the audited tree** — some memory a merge cannot rewrite alongside the content. Where
it lives, who updates it, and what happens when it legitimately diverges from disk are the
questions this leaves open, and the answer has to cover **both** rows of the table above,
including what the gate should do when it finds no reference at all — which today is to pass in
silence.

---

Happy to open PRs for any of these, or to run a fourth pilot against whatever lands.
