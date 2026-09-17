---
name: harness-audit
description: Audits and restructures a project's AI agent harness (CLAUDE.md, AGENTS.md, GEMINI.md, rules, skills, hooks, docs and Obsidian vault notes) so an agent starts each session with a short map and finds the rest on demand, then installs the guardrails that keep it that way. Expect the win in speed, consistency and blast radius rather than in tokens. Run manually with /harness-audit diagnose | apply | verify | check. Supports Claude Code, Codex, Cursor and Antigravity CLI, with or without Obsidian.
license: MIT
compatibility: Python 3.9+ and git. Full support for Claude Code, Codex, Cursor and Antigravity CLI (legacy Gemini CLI treated as Antigravity). Use a frontier model for diagnose/apply.
metadata:
  version: "1.1.0"
  source: "https://github.com/fmslutions/harness-audit"
disable-model-invocation: true
argument-hint: "diagnose | apply | verify | check"
---

# Harness audit

Goal: an agent starts each session with a small, stable map and finds everything else on demand, and the project stays that way after you leave.

Evidence to keep in mind (details in `references/principles.md`): more always-loaded instructions degrade adherence and cost; auto-generated or redundant instruction files can lower task success; so this skill **removes and relocates** more than it writes, and **measures** before and after.

`SKILL_DIR` below means the folder containing this file. Scripts need only Python and git.

## Commands

| Command | Writes | Purpose |
|---|---|---|
| `diagnose` (default) | `.harness/reports/` only | Setup interview, inventory, baseline, scorecard, change plan |
| `apply` | project files, on a git branch, after approval | Execute the approved plan, install maintenance layer |
| `verify` | `.harness/reports/` | Re-measure, lock budgets, write the final report |
| `check` | nothing | Fast maintenance lint for periodic use |

If the user gives no argument, run `diagnose`. Never run `apply` without an approved plan from `diagnose` in this project.

Write every report and question in the user's language. Keep code, file names and frontmatter keys in English.

---

## diagnose

### 1. Detect, then confirm with the user

Run `python3 SKILL_DIR/scripts/detect.py --project .` and show a short summary. It scans the repo, parent folders and common locations (Documents, iCloud Obsidian, Dropbox, OneDrive) for Obsidian vaults; if the user keeps vaults elsewhere, rerun with `--search <folder>`. Then ask, in one message, with detected answers as defaults:

1. **Agents used on this project**: Claude Code, Codex, Cursor, Antigravity CLI (Gemini CLI counts as Antigravity).
2. **Obsidian**: does this project use an Obsidian vault? List the vaults found. If yes: which vault, which folder holds this project's notes, and the topology (`inside-repo`, `repo-inside-vault`, `external`).
3. **Where agent-facing knowledge should live**: repo `docs/` (portable, versioned, works for teammates and CI) or the vault folder (single place for the human). Explain the trade-off in one sentence each; see `references/obsidian.md`.
4. **Scope of user-level files** (`~/.claude`, `~/.codex`, `~/.gemini`): include them in the measurement? They affect every project, so they are measured but never changed without explicit per-file approval.

If the user already answered some of these earlier in the conversation, do not ask again.

### 2. Safety

- Require a git repo. If there are uncommitted changes, ask the user to commit or stash first.
- Nothing is written outside `.harness/reports/` during diagnose.

### 3. Baseline

Both files below are written to disk before you discuss any number. `verify` compares
against them, and a later `apply` in a new session has nothing to stand on without them.

```bash
python3 SKILL_DIR/scripts/inventory.py --project . [--include-user] --out .harness/reports/inventory-baseline.json
python3 SKILL_DIR/scripts/measure.py snapshot --project . --label baseline [--include-user]
```

Confirm `.harness/reports/inventory-baseline.json` exists before continuing. If it is missing, rerun the command; do not proceed from numbers that live only in the conversation.

**The inventory is a lower bound, never the starting total.** It counts files. It cannot
count what plugins, MCP tool schemas, custom agents and `SessionStart` hook output add,
and that difference is large: in the first pilot the inventory read 9,288 always-on
tokens while a fresh session started at about 70,000. With `--include-user` the report
lists those sources under `user_runtime` (names and commands only, never executed, never
any env value or token), so the gap is visible instead of silent. **The authoritative
starting number is `/context` in a fresh session.** Ask for it, record it, and use it in
the report; treat the static estimate as the floor.

Ask the user for numbers the scripts cannot read, and pass them with `--manual '{...}'`:
- Claude Code: output of `/context` in a fresh session (total and Memory files section).
- Cursor: context usage shown in a fresh chat.
- Antigravity: `agy inspect` output for loaded context files, rules and skills.

Optional but recommended: agree on 3 to 5 representative tasks for this project to rerun after apply (see `references/rubric.md`, "Task benchmark").

### 4. Read the harness

Read every always-on file listed in the inventory and a sample of the largest docs. For the agents in use, read the matching `references/agents/<agent>.md`. If Obsidian is in use, read `references/obsidian.md`.

### 5. Score and plan

Score the harness with `references/rubric.md`. Then **write `.harness/reports/plan.md` to disk
before presenting anything to the user**, using the structure in `references/report-template.md`
(section "Plan"). The file is the plan; what you say in the conversation is a summary of the
file. A plan that exists only in the conversation is lost the moment the session ends, and
`apply` in a new session will refuse to run.

Also record in the plan any missing sensor: if the project has no lint command, `install.py`
installs no code sensor, and that is a gap to state explicitly, not something to paper over by
installing a check that cannot run.

Each proposed change must state: what moves, from where, to where (per `assets/templates/PLACEMENT.md`), estimated always-on tokens saved per agent, and risk level:

- **low**: frontmatter, index, links, moving files into placement folders, deleting exact duplicates generated by tools.
- **medium**: moving content out of entry files into rules, skills or docs; scoping rules; converting prose rules into hooks or lint.
- **high**: merging or rewriting knowledge, archiving notes, anything outside the repo (user-level files, the vault when external).

Rules for the plan:
- Prefer relocation over rewriting. Keep the user's wording when moving content.
- Entry file target: a map, not an encyclopedia. One canonical `AGENTS.md` for all agents; `CLAUDE.md` starts with `@AGENTS.md` plus only Claude-specific lines; `GEMINI.md` should not repeat `AGENTS.md`.
- Remove what agents can discover by themselves (directory listings, dependency lists, generic advice). Keep non-obvious commands, gotchas, and conventions that differ from defaults.
- Anything that must always happen becomes a hook, linter or CI step, not a sentence.
- Never plan to delete knowledge. Superseded content gets `status: superseded`.

Present the scorecard and a summary of the plan grouped by risk, and say where the file is.
Ask the user to approve: low as a batch, medium per group, high item by item. Write the
approvals back into `plan.md` as they come in, so the decisions survive the session too.

---

## apply

0. Require the approved plan on disk. Read `.harness/reports/plan.md`; a baseline at
   `.harness/reports/inventory-baseline.json` should be there too. If `plan.md` is missing,
   refuse and say exactly this: the file `.harness/reports/plan.md` does not exist, so there is
   no approved plan in this project; recreate it by running `/harness-audit diagnose`, which
   writes the plan and the baseline before asking for approval. Never reconstruct the plan from
   memory or from the conversation.
1. `git switch -c harness-audit/<date>`.
2. Install the maintenance layer (dry run first, show the output, then apply):
   ```bash
   python3 SKILL_DIR/scripts/install.py --project . --agents <list> --docs-dir <dir> \
     [--vault-path <vault> --vault-topology <t>] --entry-blocks --with-precommit [--with-ci]
   python3 SKILL_DIR/scripts/install.py ... --apply
   ```
   The pre-commit goes into `.githooks/` (tracked by git) and `core.hooksPath` is pointed at it,
   so a clone gets the sensor and CI is not the only gate. Two cases where the installer steps
   back and tells you instead: `core.hooksPath` already points somewhere else (husky), where it
   installs there and changes nothing; and untracked executable hooks already in `.git/hooks`,
   where it installs nothing, because setting `core.hooksPath` would silently disable them.
   Relay that message to the user and let them decide. With a `package.json` present, a
   `prepare` script arms the hooks on `npm install`, and the entry file documents the manual
   command for everyone else.
3. Execute only approved plan items. Move scoped rules into `.harness/rules/` and procedures into `.harness/skills/`. Add frontmatter to docs. Slim entry files.
4. Regenerate and check:
   ```bash
   python3 .harness/scripts/sync.py
   python3 .harness/scripts/build_index.py
   python3 .harness/scripts/lint.py
   ```
   Fix errors. Warnings may remain only if listed in the report with a reason.
5. Append to the docs log: `## [YYYY-MM-DD] audit | harness restructured (see .harness/reports/)`.
6. Commit in small, reviewable commits (install, relocation, entry files). Do not merge: the user reviews the branch.

For agent-specific install steps (Codex hook trust, Antigravity hook schema, Cursor restart), follow `references/agents/<agent>.md`.

---

## verify

1. Ask the user to open a fresh session in each agent and share the same manual numbers as the
   baseline. The comparison that matters is `/context` before against `/context` after: the
   script totals are a lower bound and miss plugins, MCP servers, agents and hook output.
2. `python3 .harness/scripts/measure.py snapshot --label after --manual '{...}'`
3. `python3 .harness/scripts/measure.py compare --before baseline --after after`
4. If task benchmarks were agreed, rerun them in fresh sessions and record success, turns and context.
5. If always-on context went up for any agent, or benchmarks got worse, say so plainly and propose a rollback of the responsible change.
6. Lock the new budgets so they can only shrink: `python3 .harness/scripts/lint.py --update-lock`.
7. Write `.harness/reports/HARNESS-REPORT.md` with `references/report-template.md` (section "Final report").

---

## check

`python3 .harness/scripts/lint.py` (or `SKILL_DIR/scripts/lint.py` if not installed yet), plus
`python3 .harness/scripts/code_sensor.py` when a code sensor is installed. Summarize findings by severity, propose fixes, and suggest a full `diagnose` when budgets are breached (`H002`, `H006`, `H015`) or more than 10 warnings accumulated.

## Reference files

- `references/principles.md`: why this design (context rot, instruction budget, progressive disclosure, guides and sensors). Read once per audit.
- `references/rubric.md`: scorecard criteria, thresholds, task benchmark method.
- `references/obsidian.md`: vault topologies and how agents reach notes.
- `references/agents/claude-code.md`, `codex.md`, `cursor.md`, `antigravity.md`: what each agent loads and how its hooks work.
- `references/report-template.md`: plan and final report structure.
- `assets/templates/PLACEMENT.md`: the placement map installed into the project.
- `scripts/code_sensor.py`: per-file ratchet over the project's own linter (fails only when a file gets worse). Configured under `code_sensor` in `.harness/config.json`.
