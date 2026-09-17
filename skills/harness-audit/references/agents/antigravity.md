# Antigravity CLI (successor of Gemini CLI)

Google retired Gemini CLI for individual accounts on 18 June 2026 in favor of Antigravity CLI (`agy`). Enterprise Gemini Code Assist licenses kept Gemini CLI. Treat both with this adapter. Checked September 2026; Antigravity changes fast, verify with `agy inspect`.

## What loads
| Layer | Files | Notes |
|---|---|---|
| Always | `~/.gemini/GEMINI.md` | global context |
| Always | `GEMINI.md` and `AGENTS.md` in the workspace | both are read: duplicated content is paid twice (lint H011) |
| Likely always | `.agents/rules/*.md` | workspace rules; confirm with `agy inspect` |
| Always | skill descriptions in `.agents/skills/` | global skills under Antigravity's own directory |
| Config | `.agents/hooks.json`, `.agents/mcp_config.json`; global under `~/.gemini/config/` | |

Antigravity reads GEMINI.md literally (no `@import` expansion); legacy Gemini CLI expanded imports. Use plain paths.
Reports indicate headless `agy -p` may not load file-based context: do not rely on it for measurement.

## Measure
No stable transcript format documented. Record numbers from `agy inspect` and session stats as manual values.

## Hooks (experimental)
Event names and schema vary across `agy` versions (reported names include SessionStart, AfterTool, AfterAgent, and PreToolUse-style decisions). The installer writes `.agents/hooks.harness.example.json`; adapt it to your version, rename to `.agents/hooks.json`, restart, verify. Until verified, the guaranteed gates are the git pre-commit hook and CI.

## Canonical layout
- Keep `AGENTS.md` canonical. If `GEMINI.md` exists, reduce it to Antigravity-specific lines or remove duplication.
- Rules: no path-scoped equivalent documented; `sync.py` writes a routing table into `AGENTS.md`/`GEMINI.md` instead of projecting rules into `.agents/rules/` (which would load always).
- Skills: `.harness/skills/<name>/` → `.agents/skills/<name>/` (shared with Codex).

## Migrating a legacy Gemini CLI project
`mv .gemini/skills .agents/skills`; `agy plugin import gemini` for extensions; MCP servers move to `mcp_config.json` (remote `url` becomes `serverUrl`).
