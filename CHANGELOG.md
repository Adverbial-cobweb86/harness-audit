# Changelog

## [Unreleased]

Three fixes from the first real pilot (a Next.js site audited with Claude Code and Codex).

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
