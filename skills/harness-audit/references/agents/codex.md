# Codex (CLI, IDE, app)

Checked against developers.openai.com/codex docs, September 2026.

## What loads
| Layer | Files | Notes |
|---|---|---|
| Always | `~/.codex/AGENTS.override.md` or `~/.codex/AGENTS.md` (first non-empty) | global |
| Always | from git root down to the launch dir: `AGENTS.override.md`, else `AGENTS.md`, else names in `project_doc_fallback_filenames` (one per dir) | concatenated root first |
| Cap | `project_doc_max_bytes`, default 32 KiB | content past the cap is dropped silently (lint H006) |
| Always | skill names and descriptions | `.agents/skills/` in the repo, user skills per Codex docs |
| On demand | skill bodies, docs | |

No `@import`: a routing table with plain paths is the only way to point at detail.
Nested `AGENTS.md` load only if Codex starts inside that directory, not when files there are read. Prefer a single root map plus scoped docs.

## Measure
Transcripts: `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`, `token_count` events, filtered by `cwd` (transcripts.py). Also `/status` in the TUI.

## Hooks installed (`.codex/hooks.json`, Claude-style schema)
Codex supports a smaller event set than Claude Code (SessionStart, PreToolUse, PermissionRequest, PostToolUse, UserPromptSubmit, Stop; newer builds add compaction events).
| Event | Matcher | Effect |
|---|---|---|
| PostToolUse | `apply_patch\|Edit\|Write` | lint files named in the patch |
| Stop | | ask to fix index/log before finishing (loop-guarded) |
| SessionStart | `startup\|resume\|clear` | alert on budget breach |
Codex asks you to trust hooks (`/hooks`). If project-level hooks are not picked up by your version, copy the entries to `~/.codex/hooks.json`. The git pre-commit gate works regardless.

## Canonical layout
`AGENTS.md` is the canonical entry file for all agents in this skill. Keep it well under the cap (default budget 120 lines).
