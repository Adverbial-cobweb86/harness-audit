<!-- Installed by harness-audit. Project-specific: adjust folders in .harness/config.json "placement". -->
# Where everything goes

Read this before creating, moving or updating any instruction or knowledge file.
Paths under `docs/` are relative to the docs root configured in `.harness/config.json` (it may be an Obsidian vault folder).

| If the information is... | It goes in | Never in |
|---|---|---|
| True for every session (build/test commands, global conventions, non-obvious gotchas) | `AGENTS.md` (Claude reads it via `@AGENTS.md` in `CLAUDE.md`) | long explanations, history |
| Only relevant to one area of the code | `.harness/rules/<area>.md` with `paths:`, then `sync.py` | entry files |
| A multi-step procedure to repeat | `.harness/skills/<name>/SKILL.md`, then `sync.py` | entry files, rules |
| Something that must always happen (format, test, block) | a hook, linter or CI check | prose instructions |
| An architecture or product decision | `docs/decisions/NNNN-title.md` | chat, entry files |
| Work in progress | `docs/plans/active/<plan>.md`, moved to `plans/completed/` when done | entry files |
| Domain knowledge, system maps | `docs/architecture/` or `docs/product/` | entry files |
| Long reference material (API dumps, specs) | `docs/references/` | anything always loaded |
| Operational procedure for humans and agents | `docs/runbooks/` | rules |
| Raw sources (transcripts, clippings, exports) | `docs/raw/` (immutable, never edited) | compiled docs |
| Status, dates, "currently working on" | the plan file or `docs/log.md` | `AGENTS.md`, `CLAUDE.md`, `GEMINI.md` |
| Personal preferences of one developer | `CLAUDE.local.md` or the agent's own memory | shared files |

## Every doc needs frontmatter

```yaml
---
description: One line saying what this is (shown in the index)
read_when: When an agent should open it (e.g. "changing billing logic")
status: active        # active | draft | superseded | archived | completed
updated: 2026-01-31
---
```

## Protocol for every change

1. Search the index first. Update an existing doc instead of creating a near-duplicate.
2. Put new content where the table says. If nothing fits, ask the user before inventing a folder.
3. Never delete knowledge: set `status: superseded` and link to the replacement.
4. Canonical rules and skills live in `.harness/`. Never edit generated copies in `.claude/`, `.cursor/`, `.agents/`.
5. When done: run `python3 .harness/scripts/sync.py`, `python3 .harness/scripts/build_index.py`, append one line to `docs/log.md`, then `python3 .harness/scripts/lint.py`.
6. Do not grow always-on files. If something truly belongs there, remove something else or ask for a budget change.
