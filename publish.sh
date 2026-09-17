#!/usr/bin/env bash
# Publish this repository to your GitHub account as a public repo with a v1.0.0 release.
# Requirements: git, python3, GitHub CLI (gh) logged in: `gh auth login`.
# Usage: bash publish.sh [repo-name]        (default: harness-audit)
set -euo pipefail
cd "$(dirname "$0")"
NAME="${1:-harness-audit}"

command -v gh >/dev/null || { echo "Install GitHub CLI first: https://cli.github.com (macOS: brew install gh)"; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "Log in first: gh auth login"; exit 1; }
LOGIN="$(gh api user -q .login)"
if gh repo view "$LOGIN/$NAME" >/dev/null 2>&1; then
  echo "Repository $LOGIN/$NAME already exists. Choose another name: bash publish.sh other-name"; exit 1
fi

echo "Publishing as $LOGIN/$NAME"
python3 - "$LOGIN" "$NAME" <<'PY'
import pathlib, sys
login, name = sys.argv[1], sys.argv[2]
for p in pathlib.Path(".").rglob("*"):
    if p.is_file() and p.suffix in {".md", ".tmpl", ".yml", ".json", ".py", ".sh"} and ".git" not in p.parts and p.name != "publish.sh":
        t = p.read_text(encoding="utf-8")
        n = t.replace("OWNER/harness-audit", f"{login}/{name}")
        if n != t:
            p.write_text(n, encoding="utf-8")
PY

echo "Running tests..."
bash tests/smoke.sh
python3 tools/build_dist.py

if [ ! -d .git ]; then
  git init -q -b main
fi
git add -A
git commit -qm "harness-audit v1.0.0" || true

gh repo create "$LOGIN/$NAME" --public --source . --remote origin --push \
  --description "Agent Skill that audits, restructures and keeps organized the harness of AI coding projects (Claude Code, Codex, Cursor, Antigravity, Obsidian). Measures context before and after."
gh repo edit "$LOGIN/$NAME" --homepage "https://github.com/$LOGIN/$NAME#readme" \
  --add-topic agent-skills --add-topic claude-code --add-topic claude-skills --add-topic codex \
  --add-topic cursor --add-topic antigravity --add-topic obsidian --add-topic context-engineering \
  --add-topic harness-engineering --add-topic ai-agents --add-topic agents-md --add-topic llm

awk '/^## \[1.0.0\]/{f=1;next} /^## \[/{f=0} f' CHANGELOG.md > /tmp/harness-release-notes.md
gh release create v1.0.0 dist/harness-audit.zip dist/harness-keeper.zip \
  --repo "$LOGIN/$NAME" --title "harness-audit v1.0.0" --notes-file /tmp/harness-release-notes.md

echo
echo "Done: https://github.com/$LOGIN/$NAME"
