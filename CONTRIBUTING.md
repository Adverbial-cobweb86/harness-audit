# Contributing

Thanks for helping. The most useful contributions right now:

1. **Results from real projects.** Open a results issue with your before/after table. These numbers calibrate the default budgets.
2. **Agent adapter fixes.** Loading rules and hook schemas change often, especially in Antigravity. Include the agent version and a link to the docs you checked.
3. **Bug reports** with the output of `python3 .harness/scripts/lint.py --json` and the agent you used.

## Development

```bash
bash tests/smoke.sh          # end-to-end test on a throwaway fixture
python3 tools/build_dist.py  # builds and validates the upload packages
```

Guidelines:

- Scripts use only the Python standard library and must run on Python 3.9+.
- Hooks must never break an agent session: on internal errors they exit 0.
- Keep `skills/harness-keeper/SKILL.md` and `skills/harness-audit/assets/templates/harness-keeper-skill.tmpl` identical (the smoke test checks it).
- Every change to agent behavior updates `skills/harness-audit/references/agents/<agent>.md` with the date it was verified.
- Keep `SKILL.md` frontmatter within the Agent Skills standard for upload packages; Claude Code extensions are stripped by `build_dist.py`.
- Write docs in plain language. The skill preaches short, high-signal instructions, so its own files should too.
