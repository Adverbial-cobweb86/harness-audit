# Principles behind harness-audit

Sources are listed at the end. Checked September 2026.

## The constraint
- **Context rot.** Chroma tested 18 frontier models: reliability drops as input length grows, even on simple tasks, long before the window is full.
- **Attention budget.** Anthropic treats context as a finite resource with diminishing returns: find the smallest set of high-signal tokens.
- **Instruction budget.** HumanLayer estimates frontier models follow roughly 150 to 200 instructions reliably, and the agent's own system prompt already uses a share of that.
- **Smart zone.** Dex Horthy (HumanLayer) observes quality degrading non-linearly as a session fills; the remedy is intentional compaction into markdown artifacts and fresh sessions.
- **More docs can hurt.** ETH Zurich's evaluation of AGENTS.md files found auto-generated files reduced task success and raised cost, and codebase overviews did not speed up navigation. Instructions are followed, so unnecessary ones make tasks harder.

Implication: the audit removes and relocates first, writes last, and measures.

## Design rules
1. **Map, not encyclopedia** (OpenAI harness engineering). A short entry file points to a docs directory that is the system of record.
2. **Compiled knowledge with index and log** (Karpathy LLM Wiki). Raw sources immutable; compiled notes maintained by agents; `index.md` catalogs, `log.md` records chronology; periodic lint for orphans, contradictions and stale claims.
3. **Progressive disclosure.** Always-on (entry files) → conditional (path-scoped rules) → on demand (docs, skill bodies).
4. **One source of truth per fact.** Canonical rules and skills in `.harness/`, projected to each agent's format by `sync.py`.
5. **Guides and sensors** (Birgitta Böckeler, martinfowler.com). Instructions are feedforward and probabilistic; hooks, linters and CI are feedback and deterministic. Anything that must always happen becomes a sensor.
6. **Stable prefix** (Manus). Keep volatile content (dates, status, current work) out of always-on files so the prompt prefix stays cacheable; compress restorably (keep the path, drop the content).
7. **Subagents for exploration.** Heavy reading happens in isolated contexts; only summaries return.
8. **Ratchet.** Once reduced, budgets are locked and may only shrink without explicit approval.

## Sources
- Anthropic, Effective context engineering for AI agents
- Anthropic, Claude Code docs: memory, skills, hooks, context window
- OpenAI, Harness engineering: leveraging Codex in an agent-first world
- Andrej Karpathy, llm-wiki (gist, April 2026)
- Chroma, Context Rot: How Increasing Input Tokens Impacts LLM Performance (2025)
- HumanLayer, Writing a good CLAUDE.md; Dex Horthy talks on research-plan-implement
- Philipp Schmid, Writing a Good AGENTS.md (summary of ETH Zurich evaluation)
- Yichao Ji (Manus), Context Engineering for AI Agents: Lessons from Building Manus
- Birgitta Böckeler, Harness engineering for coding agent users (martinfowler.com)
