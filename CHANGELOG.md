# Changelog

## [1.3.0] - 2026-09-18

**New rule: the skill never cleans a working tree** — not with a generic approval, not inside
`apply`. It surveys, presents the evidence and the named options, and the user decides.

- An unclean working tree is now surveyed before anyone is asked to clean it. In both pilots
  what sat uncommitted was real work — a submodule pointer carrying a whole release of another
  repository, tag included, and a month-old stash that took a line-by-line comparison to prove
  redundant — and both times it was the agent's own initiative that found out. `diagnose` now
  presents, per item: untracked build output grouped by root directory with the `.gitignore`
  line it would need, an advanced submodule pointer with the commits and tags between the
  recorded pointer and the current one, modified files with lines changed and age, other
  untracked files with size and date, and stashes with date, files and lines. Each item carries
  the read-only command that shows the evidence. Then the options are named in order — commit,
  stash, discard — with discard last and marked as the only irreversible one.
  New `scripts/dirty.py`, folded into `detect.py --git-only` so `apply` sees the same survey.
- Written as a rule in `SKILL.md`: the skill never cleans a working tree. Not with a generic
  approval, not inside `apply`. The survey is read-only and runs no `stash`, `checkout`,
  `clean`, `reset`, `add` or `commit`, and it does not edit `.gitignore`.
- The survey carries no file content, and the text the user wrote (a stash message, a submodule
  commit subject, a filename) is clipped to 80 characters and passed through the secret mask
  before it reaches `.harness/reports/`. Categories are capped at 20 items with the remainder
  counted, and a survey slower than 2 seconds reports counts only.

## [1.2.0] - 2026-09-18

Three fixes from the second pilot: a large product repository with a submodule, 25 worktrees,
several sessions shipping pull requests in parallel and two agents.

### Change for projects installed with 1.1.0

The opening budgets now come from the measured project instead of the fixed defaults, so a
project carrying legacy no longer starts with a red gate; an existing `.harness/config.json` is
untouched until you rerun `install.py`.

### Fixes

- The safety check now looks at the remote. `diagnose` stops when the branch is behind its
  upstream, saying how many commits are missing and which command brings them, and stops on a
  divergence without proposing a rebase, because in a repository with parallel sessions that
  call belongs to the user. With no `@{upstream}` it falls back to `origin/HEAD`, and only
  records the absence when there is neither. `apply` reruns the same check, since it often runs
  in a later session: `detect.py --git-only` prints just the git state for that.
  In the pilot the baseline was measured on a branch 48 commits behind, against a `CLAUDE.md` of
  11,015 lines while the remote had 13,071, and it only surfaced mid-`apply`.
  No script fetches: writing to the network inside someone else's repository, unasked, is not
  this skill's call. Instead the answer carries its own age (`reference_age_days`), and a
  `behind: 0` measured against a reference a day or more old is flagged (`stale_comparison`)
  with a one-line note to run `git fetch`, because that false comfort is what the pilot hit.
- `install.py` sets the opening budgets from what the project measures after installation,
  never looser than the targets, and marks them `budgets_transitional`. A gate installed at the
  default budget over a legacy harness is red on its first run and blocks the very commits that
  are shrinking it. `lint.py` warns (`H019`) on every run while the mark is there, so a
  transitional budget cannot quietly become permanent, and `lint.py --update-lock` tightens the
  budgets to the real values, printing the before and after per budget and per agent.
- All git reads whose format the scripts parse now call the real binary (`/usr/bin/git`, or the
  first `git` on PATH when that is missing). A wrapper on PATH broke the worktree parser in the
  pilot by returning the human format for `git worktree list --porcelain`. Reports carry
  `git_environment`, which flags a different `git` sitting first on PATH.

## [1.1.0] - 2026-09-17

Three fixes from the first real pilot (a Next.js site audited with Claude Code and Codex).

### Breaking change for projects installed with 1.0.0

The pre-commit is now installed into `.githooks/` and armed with `core.hooksPath`, instead of
`.git/hooks/`, which git does not version: in the pilot the sensor existed only on the machine
that ran `apply`, a clone got nothing, and there was no CI. A project set up with 1.0.0 keeps
working, but its hook stays unversioned. To migrate, rerun `install.py --with-precommit --apply`
from the 1.1.0 skill after moving any hook of your own out of `.git/hooks/` (the installer
refuses to touch an active `.git/hooks` and an existing `core.hooksPath`, husky included, and
tells you instead).

### Also in this release

- Skill description now states what the pilot measured: task success unchanged, context per task
  down 8%, time down about fivefold, side effects from 6 to 0.

- `diagnose` now writes `.harness/reports/plan.md` and `inventory-baseline.json` to disk **before**
  presenting anything; the conversation is a summary of the file. `apply` refuses without the plan
  and names the missing file and the command that recreates it. In the pilot the plan existed only
  in the conversation and had to be rebuilt by hand in the next session.
- `install.py` installs the pre-commit into `.githooks/` (tracked by git) and points `core.hooksPath`
  at it, adds an npm `prepare` script and documents the manual command in the entry file, so a clone
  gets the sensor. It steps back and warns instead of taking over when `.git/hooks` already holds
  active hooks, and installs into an existing `core.hooksPath` (husky) rather than replacing it.
  The CI workflow runs `sync --check`, the harness lint and the code sensor.
- New `scripts/code_sensor.py`: a per-file ratchet over the project's own linter, ESLint by default
  when a `package.json` is present, any tool that lists problems per file otherwise. It fails only
  when a file goes above its own baseline, because a binary gate is unusable on a codebase with
  pre-existing problems. No lint command means no sensor, and `diagnose` records that as a gap.
- `inventory.py --include-user` now lists enabled plugins, custom and plugin agents, MCP server
  names and `SessionStart` hook commands, and labels its own total a lower bound: the pilot's
  inventory read 9,288 always-on tokens against a real session start of about 70,000. Hooks are
  never executed, MCP entries carry names only, and env values, headers, URLs and any
  `token=`/`key=`/`secret=`/`password=` pair are masked out of the report.

## [1.0.0] - 2026-09-17

First public release.

- `harness-audit` skill with `diagnose`, `apply`, `verify` and `check`.
- `harness-keeper` skill installed into projects for every agent.
- Adapters for Claude Code, Codex, Cursor and Antigravity CLI (legacy Gemini CLI handled by Antigravity).
- Obsidian support: vault detection, three layouts, generated index from frontmatter.
- Deterministic scripts: inventory, lint (H001 to H018), sync, index, hooks, measurement, transcripts.
- Maintenance layer: placement map, post-edit and stop hooks, git pre-commit, optional GitHub Actions.
- Ratchet on always-on budgets.
- Upload-ready packages validated for a single `SKILL.md` with standard frontmatter.
