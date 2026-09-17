# Canonical scoped rules

One file per area. After editing, run `python3 .harness/scripts/sync.py`.

```markdown
---
description: API route conventions
paths:
  - "src/api/**/*.ts"
---
- Validate every request body at the route boundary.
```

Generated copies: `.claude/rules/*.md` (paths), `.cursor/rules/*.mdc` (globs).
Codex and Antigravity have no path-scoped rules: they get a routing table in AGENTS.md/GEMINI.md.
