# Claude Code

Checked against code.claude.com docs, September 2026. Re-verify when Claude Code changes.

## What loads
| Layer | Files | Notes |
|---|---|---|
| Always | `CLAUDE.md`, `.claude/CLAUDE.md`, `CLAUDE.local.md` in the launch dir and every parent; `~/.claude/CLAUDE.md` | Concatenated, not overridden. Target under 200 lines each. Files over 4 MiB are skipped. |
| Always | everything `@imported` by those files (max depth 4) | Imports organize but do not reduce context. |
| Always | `.claude/rules/**/*.md` and `~/.claude/rules/` without `paths` | Same priority as `.claude/CLAUDE.md`. |
| Always | auto memory `MEMORY.md`: first 200 lines or 25KB | `~/.claude/projects/<encoded path>/memory/`. Topic files load on demand. |
| Always | skill name + description for skills Claude may invoke | `disable-model-invocation: true` removes the description from context. |
| Always | MCP tool names and server instructions | Tool schemas are deferred and loaded via tool search. |
| Conditional | `.claude/rules` with `paths:`; `CLAUDE.md` in subdirectories | Load when Claude reads matching files. |
| On demand | skill bodies and references, docs, files read | |

HTML block comments in CLAUDE.md are stripped before injection: use them for maintainer notes.
Claude Code reads `CLAUDE.md`, not `AGENTS.md`: put `@AGENTS.md` at the top of `CLAUDE.md`.
After `/compact`, root CLAUDE.md is re-read; path-scoped rules reload when files match again.

## Measure
- `/context` in a fresh session: total and Memory files list.
- Transcripts: `~/.claude/projects/<encoded path>/*.jsonl` (transcripts.py). Use input and cache tokens; output tokens are under-counted in JSONL.
- Optional: OpenTelemetry (`CLAUDE_CODE_ENABLE_TELEMETRY=1`).

## Hooks installed (`.claude/settings.json`)
| Event | Matcher | Effect |
|---|---|---|
| PostToolUse | `Write\|Edit\|MultiEdit\|NotebookEdit` | lint the edited file; exit 2 sends fixes to Claude |
| Stop | | blocks the end of a turn if docs changed without index/log, once per turn (`stop_hook_active`) |
| SessionStart | `startup\|resume\|clear\|compact` | one-line alert only when budgets are breached |

Only exit code 2 blocks; exit 1 is a non-blocking error. Hooks in project settings need workspace trust.

## Skills location
Project `.claude/skills/<name>/`, personal `~/.claude/skills/<name>/`.
