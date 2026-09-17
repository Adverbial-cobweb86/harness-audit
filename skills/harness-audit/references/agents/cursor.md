# Cursor

Checked against cursor.com/docs (rules, hooks), September 2026.

## What loads
| Layer | Files | Notes |
|---|---|---|
| Always | `AGENTS.md` in the project root (nested AGENTS.md scope to their folder) | plain markdown alternative to rules |
| Always | `.cursor/rules/*.mdc` with `alwaysApply: true` | full content every chat |
| Always | description of "Apply Intelligently" rules (`alwaysApply: false`, description, no globs) | body loads when the agent decides |
| Conditional | rules with `globs` | attach when matching files are in context |
| Manual | rules without description/globs | only via `@rule-name` |
| Always | User Rules from Cursor settings | not on disk: review manually |
| Legacy | `.cursorrules` | deprecated: migrate |
| Always | skill descriptions in `.cursor/skills/` | Cursor 2.4+ can convert intelligent rules to skills (`/migrate-to-skills`) |

`.md` files inside `.cursor/rules` are ignored: rules must be `.mdc` with frontmatter (lint H005).

## Measure
No stable local transcript. Record the context indicator from a fresh chat as a manual number.

## Hooks installed (`.cursor/hooks.json`, `version: 1`)
| Event | Effect |
|---|---|
| afterFileEdit | records edited harness files (this event cannot message the agent) |
| stop | if problems remain, returns `followup_message` so the agent continues and fixes them (loop-guarded) |
| sessionStart | returns `additional_context` only on budget breach |
Restart Cursor after installing hooks. Some hooks do not run in cloud agents; pre-commit and CI cover that.

## Projections from `.harness/`
- `.harness/rules/<area>.md` → `.cursor/rules/<area>.mdc` with `globs` and `alwaysApply: false`.
- `.harness/skills/<name>/` → `.cursor/skills/<name>/`.
