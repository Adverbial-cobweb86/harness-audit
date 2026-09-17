#!/usr/bin/env bash
# End-to-end smoke test on a throwaway fixture. Usage: bash tests/smoke.sh
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
S="$REPO/skills/harness-audit/scripts"
T="$(mktemp -d)"; P="$T/proj"; mkdir -p "$P" && cd "$P"
git init -q && git config user.email t@t && git config user.name t
fail=0; check() { if [ "$1" = "$2" ]; then echo "PASS $3"; else echo "FAIL $3 (got $1, want $2)"; fail=1; fi; }

python3 - <<'PY'
import os
os.makedirs("docs/notes", exist_ok=True); os.makedirs(".claude/rules", exist_ok=True); os.makedirs(".cursor/rules", exist_ok=True)
para = "Shared paragraph long enough to be detected as duplicated content across the entry files of this fixture project."
open("CLAUDE.md","w").write(f"# P\n\n{para}\n\nCurrently migrating billing (2026-09-10).\n@docs/big.md\n" + "\n".join(f"- rule {i}" for i in range(150)))
open("AGENTS.md","w").write(f"# P\n\n{para}\n")
open("docs/big.md","w").write("x " * 30000)
open(".claude/rules/api.md","w").write("- validate\n")
PY
git add -A && git commit -qm init

python3 "$S/lint.py" >/dev/null; check $? 1 "lint flags messy fixture"
python3 "$S/measure.py" snapshot --label baseline >/dev/null; check $? 0 "baseline snapshot"
python3 "$S/install.py" --agents claude-code,codex,cursor,antigravity --entry-blocks --with-precommit --apply >/dev/null; check $? 0 "install apply"

mkdir -p docs/references .harness/rules
git mv docs/big.md docs/references/big.md
python3 - <<'PY'
p="docs/references/big.md"; s=open(p).read()
open(p,"w").write("---\ndescription: Big reference\nread_when: deep dives\nstatus: active\nupdated: 2026-09-17\n---\n"+s)
open(".harness/rules/api.md","w").write('---\ndescription: API rules\npaths:\n  - "src/api/**"\n---\n- validate\n')
open("CLAUDE.md","w").write("@AGENTS.md\n\n## Claude Code\n- plan mode for billing\n")
PY
git rm -q .claude/rules/api.md
python3 .harness/scripts/sync.py >/dev/null && python3 .harness/scripts/build_index.py >/dev/null
echo "## [2026-09-17] audit | restructured" >> docs/log.md
python3 .harness/scripts/lint.py >/dev/null; check $? 0 "lint clean after restructure"
git add -A && git commit -qm restructure; check $? 0 "pre-commit passes clean commit"

printf '# no frontmatter\n' > docs/references/new.md
printf '%s' "{\"session_id\":\"a\",\"cwd\":\"$P\",\"tool_input\":{\"file_path\":\"$P/docs/references/new.md\"}}" | python3 .harness/scripts/hook.py --agent claude-code --event post-edit 2>/dev/null; check $? 2 "claude post-edit blocks bad doc"
printf '%s' "{\"session_id\":\"b\",\"cwd\":\"$P\",\"tool_name\":\"apply_patch\",\"tool_input\":{\"command\":\"*** Begin Patch\\n*** Add File: docs/references/new.md\\n*** End Patch\"}}" | python3 .harness/scripts/hook.py --agent codex --event post-edit 2>/dev/null; check $? 2 "codex post-edit blocks bad doc"
out=$(printf '%s' "{\"conversation_id\":\"c\",\"workspace_roots\":[\"$P\"],\"loop_count\":0}" | python3 .harness/scripts/hook.py --agent cursor --event stop)
case "$out" in *followup_message*) check 1 1 "cursor stop returns followup";; *) check 0 1 "cursor stop returns followup";; esac
printf '%s' "{\"session_id\":\"a\",\"cwd\":\"$P\",\"stop_hook_active\":true}" | python3 .harness/scripts/hook.py --agent claude-code --event stop 2>/dev/null; check $? 0 "claude stop loop guard"
git add docs/references/new.md; git commit -qm bad 2>/dev/null; check $? 1 "pre-commit blocks bad doc"
rm -f docs/references/new.md; git reset -q

python3 .harness/scripts/measure.py snapshot --label after >/dev/null
cmp_out=$(python3 .harness/scripts/measure.py compare --before baseline --after after); [[ "$cmp_out" == *claude-code* ]]; check $? 0 "before/after comparison"
python3 .harness/scripts/lint.py --update-lock >/dev/null; printf '\n%s' "$(python3 -c 'print("\n".join("- extra line with plenty of words to grow tokens "*2 for _ in range(60)))')" >> AGENTS.md
lint_out=$(python3 .harness/scripts/lint.py 2>/dev/null); [[ "$lint_out" == *H015* ]]; check $? 0 "ratchet detects growth"

cmp -s "$REPO/skills/harness-keeper/SKILL.md" "$REPO/skills/harness-audit/assets/templates/harness-keeper-skill.tmpl"; check $? 0 "keeper template matches skills/harness-keeper"
python3 "$REPO/tools/build_dist.py" >/dev/null; check $? 0 "dist packages build and validate"
n=$(python3 -c "import zipfile,sys;print(sum(1 for n in zipfile.ZipFile('$REPO/dist/harness-audit.zip').namelist() if n.split('/')[-1]=='SKILL.md'))"); check "$n" 1 "upload zip has exactly one SKILL.md"
rm -rf "$T"; [ $fail -eq 0 ] && echo "ALL PASSED" || { echo "SOME FAILED"; exit 1; }
