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
After `/compact`, root CLAUDE.md is re-read; path-scoped rules reload when files match again.
A `CLAUDE.md` over **4 MiB is skipped whole** — not truncated, nothing of it loads (lint `H021`).

## Which instruction file gets read

Since v2.1.277 Claude Code can read `AGENTS.md` itself. What it reads depends on the files in
the tree and on one setting:

| In the working directory or above it | Claude reads |
|---|---|
| `AGENTS.md`, and no `CLAUDE.md`, `.claude/CLAUDE.md` or `CLAUDE.local.md` | the `AGENTS.md` files, directly |
| `AGENTS.md` **and** any of those three | the `CLAUDE.md` files only; `AGENTS.md` is ignored |
| a `CLAUDE.md` that imports `@AGENTS.md` | the `CLAUDE.md`, with `AGENTS.md` through the import |

What counts for that check: `CLAUDE.md`, `.claude/CLAUDE.md` and `CLAUDE.local.md`, in the
working directory or any directory above it. What does **not** count, and keeps loading next to
`AGENTS.md`: `~/.claude/CLAUDE.md`, the organization's managed `CLAUDE.md`, and `.claude/rules/`.

Consequence worth auditing for: `CLAUDE.local.md` is personal and gitignored, so one developer
who has one loses the team's `AGENTS.md` while the repository still looks right, and nothing
warns them (lint `H020`).

When it does read `AGENTS.md` directly, at session start it reads every `AGENTS.md` and
`.claude/AGENTS.md` from the working directory up, and a subdirectory's `AGENTS.md` when it
opens a file there and that subdirectory has none of the three `CLAUDE.md` files. Inside those
files `@path` imports expand and `claudeMdExcludes` applies. Never read, by Claude Code:
`AGENTS.local.md`, `AGENTS.override.md`, anything under `.agents/` — while Codex *does* read
`AGENTS.override.md`, and with precedence over `AGENTS.md` (lint `H022`).

### Where the direct read differs from a CLAUDE.md
- **Not listed** in `/memory` or under Memory files in `/context`. The confirmation is the
  session line `no CLAUDE.md found; AGENTS.md loaded: <path>`. So `/context` **understates** the
  always-on total by the size of that file.
- **`InstructionsLoaded` hooks do not fire** for it. They fire normally for an `AGENTS.md` that a
  `CLAUDE.md` imports or symlinks to. No sensor this skill installs depends on that event.
- An `@path` import pointing outside the working directory **loads with no dialog** if external
  imports were already approved for the project, where a `CLAUDE.md` asks. Worth knowing when
  auditing someone else's repository: the approval you gave once keeps applying, silently.
- `--add-dir` with `CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD` loads those directories'
  `CLAUDE.md`, never their `AGENTS.md`.

### The setting
`/config` → **Project instructions**, stored as
`pluginConfigs["agents-md@builtin"].options.instructionFiles`:

| Value | Claude reads |
|---|---|
| `claude-md-or-agents-md` | default: `CLAUDE.md` files, or `AGENTS.md` when none of the three exist |
| `claude-md-and-agents-md` | both, each directory's `CLAUDE.md` first, its `AGENTS.md` after |
| `claude-md` | `CLAUDE.md` files only |
| `managed-only` | only the managed `CLAUDE.md` and auto memory at launch |

Honored in **user** (`~/.claude/settings.json`), **managed** and `--settings` files only. Claude
Code **ignores it in project and local settings** — a value committed to `.claude/settings.json`
does nothing, which is its own silent failure.

### Sessions that never read AGENTS.md directly
Claude reads `CLAUDE.md` files only, and Project instructions does not appear in `/config`:
- a version before v2.1.277;
- the first session after installing or upgrading to a version that supports it;
- a session that does not fetch feature flags from Anthropic: Amazon Bedrock or another
  third-party provider, or telemetry disabled;
- `disableAllHooks` or `allowManagedHooksOnly` set;
- the built-in `agents-md` plugin disabled in `/plugin`.

None of these is readable from disk, so the audit never asserts a direct read: it reports it as
undetermined and says how to confirm. `@AGENTS.md` inside a `CLAUDE.md` is the arrangement that
works in all of them, and the import never causes a double read under any value of the setting.

## Measure
- `/context` in a fresh session: total and Memory files list. Add the `AGENTS.md` by hand when
  the session shows the `AGENTS.md loaded` line: `/context` does not count it.
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
