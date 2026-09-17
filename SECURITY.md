# Security

harness-audit runs local Python scripts and installs hooks that execute on agent events and git commits. Before installing:

- Read `skills/harness-audit/scripts/hook.py` and `install.py`. They only read and write files inside the project, the configured docs folder, and `.git/hooks/pre-commit`.
- No script makes network calls.
- `install.py` runs as a dry run unless you pass `--apply`, and it never deletes knowledge files.
- Project hooks in Claude Code, Codex and Cursor require you to trust the workspace.

To report a vulnerability, open a private security advisory on this repository instead of a public issue.
