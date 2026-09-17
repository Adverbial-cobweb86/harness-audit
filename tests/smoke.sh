#!/usr/bin/env bash
# End-to-end smoke test on a throwaway fixture. Usage: bash tests/smoke.sh
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
S="$REPO/skills/harness-audit/scripts"
T="$(mktemp -d)"; P="$T/proj"; mkdir -p "$P" && cd "$P"
git init -q && git config user.email t@t && git config user.name t
fail=0; check() { if [ "$1" = "$2" ]; then echo "PASS $3"; else echo "FAIL $3 (got $1, want $2)"; fail=1; fi; }

python3 - <<'PY'
import json, os
os.makedirs("docs/notes", exist_ok=True); os.makedirs(".claude/rules", exist_ok=True); os.makedirs(".cursor/rules", exist_ok=True)
para = "Shared paragraph long enough to be detected as duplicated content across the entry files of this fixture project."
open("CLAUDE.md","w").write(f"# P\n\n{para}\n\nCurrently migrating billing (2026-09-10).\n@docs/big.md\n" + "\n".join(f"- rule {i}" for i in range(150)))
open("AGENTS.md","w").write(f"# P\n\n{para}\n")
open("docs/big.md","w").write("x " * 30000)
open(".claude/rules/api.md","w").write("- validate\n")
open("package.json","w").write(json.dumps({"name": "fixture", "devDependencies": {"eslint": "^9"}}, indent=2) + "\n")
open("lintstub.py","w").write(
    "import pathlib\n"
    "print(pathlib.Path('lintstub.txt').read_text() if pathlib.Path('lintstub.txt').exists() else '')\n")
open("lintstub.txt","w").write("src/a.js:3:1: error x\nsrc/a.js:9:2: error y\nsrc/b.js:1:1: error z\n")
PY
git add -A && git commit -qm init

python3 "$S/lint.py" >/dev/null; check $? 1 "lint flags messy fixture"
python3 "$S/measure.py" snapshot --label baseline >/dev/null; check $? 0 "baseline snapshot"
python3 "$S/install.py" --agents claude-code,codex,cursor,antigravity --entry-blocks --with-precommit --with-ci --apply >/dev/null; check $? 0 "install apply"

# --- correction 2: sensors have to be versioned, and reach a clone
[ -x .githooks/pre-commit ]; check $? 0 "pre-commit installed in tracked .githooks"
check "$(git config --local --get core.hooksPath)" ".githooks" "core.hooksPath points at .githooks"
grep -q "core.hooksPath .githooks" package.json; check $? 0 "package.json prepare arms the hooks"
grep -q "core.hooksPath .githooks" AGENTS.md; check $? 0 "entry file documents how to arm the hooks"
[ -f .github/workflows/harness.yml ]; check $? 0 "CI workflow installed"
grep -q "code_sensor.py" .github/workflows/harness.yml; check $? 0 "CI runs the code sensor"
grep -q "hashFiles('.harness/scripts/code_sensor.py')" .github/workflows/harness.yml; check $? 0 "CI step keys off the sensor, not the baseline"
python3 -c "import json;c=json.load(open('.harness/config.json'));assert c['code_sensor']['format']=='eslint-json',c"; check $? 0 "eslint detected from package.json"
grep -q "code_sensor.py --staged" .githooks/pre-commit; check $? 0 "pre-commit runs the code sensor"

# --- the sensor is a ratchet, and works with any tool that lists problems per file
python3 - <<'PY'
import json
c = json.load(open(".harness/config.json"))
c["code_sensor"] = {"command": "python3 lintstub.py", "format": "text", "baseline": ".harness/code-baseline.json"}
json.dump(c, open(".harness/config.json", "w"), indent=2)
PY
python3 .harness/scripts/code_sensor.py >/dev/null; check $? 0 "sensor creates the baseline on first run"
python3 -c "import json;b=json.load(open('.harness/code-baseline.json'));assert b=={'src/a.js':2,'src/b.js':1},b"; check $? 0 "baseline counts problems per file"
python3 .harness/scripts/code_sensor.py >/dev/null; check $? 0 "sensor passes with pre-existing problems"
printf 'src/a.js:3:1: error x\nsrc/a.js:9:2: error y\nsrc/a.js:12:2: error w\nsrc/b.js:1:1: error z\n' > lintstub.txt
python3 .harness/scripts/code_sensor.py >/dev/null; check $? 1 "sensor fails when one file gets worse"
printf 'src/b.js:1:1: error z\n' > lintstub.txt
python3 .harness/scripts/code_sensor.py >/dev/null; check $? 0 "sensor passes when a file improves"
python3 -c "import json;b=json.load(open('.harness/code-baseline.json'));assert b=={'src/b.js':1},b"; check $? 0 "ratchet tightens the baseline after an improvement"
python3 - <<'PY'
import json
c = json.load(open(".harness/config.json")); c.pop("code_sensor")
json.dump(c, open(".harness/config.json", "w"), indent=2)
PY
python3 .harness/scripts/code_sensor.py >/dev/null; check $? 2 "sensor reports misconfiguration instead of passing"
rm -f .harness/code-baseline.json lintstub.txt

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
git add -A && git commit -qm restructure; check $? 0 "tracked pre-commit passes a clean commit (sensor unconfigured does not block)"

printf '# no frontmatter\n' > docs/references/new.md
printf '%s' "{\"session_id\":\"a\",\"cwd\":\"$P\",\"tool_input\":{\"file_path\":\"$P/docs/references/new.md\"}}" | python3 .harness/scripts/hook.py --agent claude-code --event post-edit 2>/dev/null; check $? 2 "claude post-edit blocks bad doc"
printf '%s' "{\"session_id\":\"b\",\"cwd\":\"$P\",\"tool_name\":\"apply_patch\",\"tool_input\":{\"command\":\"*** Begin Patch\\n*** Add File: docs/references/new.md\\n*** End Patch\"}}" | python3 .harness/scripts/hook.py --agent codex --event post-edit 2>/dev/null; check $? 2 "codex post-edit blocks bad doc"
out=$(printf '%s' "{\"conversation_id\":\"c\",\"workspace_roots\":[\"$P\"],\"loop_count\":0}" | python3 .harness/scripts/hook.py --agent cursor --event stop)
case "$out" in *followup_message*) check 1 1 "cursor stop returns followup";; *) check 0 1 "cursor stop returns followup";; esac
printf '%s' "{\"session_id\":\"a\",\"cwd\":\"$P\",\"stop_hook_active\":true}" | python3 .harness/scripts/hook.py --agent claude-code --event stop 2>/dev/null; check $? 0 "claude stop loop guard"
git add docs/references/new.md; git commit -qm bad 2>/dev/null; check $? 1 "tracked pre-commit blocks bad doc"
rm -f docs/references/new.md; git reset -q

python3 .harness/scripts/measure.py snapshot --label after >/dev/null
cmp_out=$(python3 .harness/scripts/measure.py compare --before baseline --after after); [[ "$cmp_out" == *claude-code* ]]; check $? 0 "before/after comparison"
python3 .harness/scripts/lint.py --update-lock >/dev/null; printf '\n%s' "$(python3 -c 'print("\n".join("- extra line with plenty of words to grow tokens "*2 for _ in range(60)))')" >> AGENTS.md
lint_out=$(python3 .harness/scripts/lint.py 2>/dev/null); [[ "$lint_out" == *H015* ]]; check $? 0 "ratchet detects growth"

# --- correction 2: an existing hook setup is never taken over silently
H="$T/husky"; mkdir -p "$H/.husky" && git -C "$H" init -q && git -C "$H" config user.email t@t && git -C "$H" config user.name t
git -C "$H" config core.hooksPath .husky && printf '#!/bin/sh\nnpm test\n' > "$H/.husky/pre-commit"
python3 "$S/install.py" --project "$H" --agents claude-code --with-precommit --apply >/dev/null
grep -q "harness-audit" "$H/.husky/pre-commit"; check $? 0 "husky: hook installed into the configured hooksPath"
[ ! -d "$H/.githooks" ]; check $? 0 "husky: .githooks not imposed"
check "$(git -C "$H" config --local --get core.hooksPath)" ".husky" "husky: core.hooksPath left untouched"
grep -q "npm test" "$H/.husky/pre-commit"; check $? 0 "husky: existing hook content preserved"

G="$T/legacy"; mkdir -p "$G" && git -C "$G" init -q && git -C "$G" config user.email t@t && git -C "$G" config user.name t
printf '#!/bin/sh\necho mine\n' > "$G/.git/hooks/pre-commit" && chmod +x "$G/.git/hooks/pre-commit"
gout=$(python3 "$S/install.py" --project "$G" --agents claude-code --with-precommit --apply)
case "$gout" in *"SKIP   pre-commit"*) check 1 1 "legacy hooks: install warns instead of taking over";; *) check 0 1 "legacy hooks: install warns instead of taking over";; esac
[ -z "$(git -C "$G" config --local --get core.hooksPath)" ]; check $? 0 "legacy hooks: core.hooksPath not set"
grep -q "harness-audit" "$G/.git/hooks/pre-commit"; check $? 1 "legacy hooks: existing hook untouched"

# --- correction 3: user runtime is inventoried, and no secret ever reaches the report
FH="$T/home"
mkdir -p "$FH/.claude/agents" "$FH/.claude/plugins/marketplaces/mkt" \
         "$FH/.claude/plugins/cache/mkt/realplug/1.0.0/agents" \
         "$FH/.claude/plugins/cache/mkt/realplug/1.0.0/hooks"
python3 "$REPO/tests/fake_home.py" "$FH"
inv=$(HOME="$FH" python3 "$S/inventory.py" --project "$P" --include-user)
grep -q '"realplug@mkt"' <<<"$inv"; check $? 0 "inventory lists enabled plugins"
grep -q '"installed": false' <<<"$inv"; check $? 0 "inventory marks an enabled plugin missing from disk"
grep -q 'catalogonly' <<<"$inv"; check $? 1 "inventory ignores marketplace catalogs"
grep -q 'offplug' <<<"$inv"; check $? 1 "inventory ignores disabled plugins"
grep -q '1.0.0.bak' <<<"$inv"; check $? 1 "inventory ignores .bak copies"
grep -q 'reviewer' <<<"$inv" && grep -q 'planner' <<<"$inv"; check $? 0 "inventory lists user and plugin agents"
grep -q '"supabase"' <<<"$inv" && grep -q '"plugmcp"' <<<"$inv"; check $? 0 "inventory lists MCP server names"
grep -q 'plugboot.mjs' <<<"$inv"; check $? 0 "inventory lists SessionStart hook commands"
grep -qE 'SECRET-(ENV|HEADER|CMD|PLUGIN)-VALUE' <<<"$inv"; check $? 1 "inventory leaks no secret from env, headers or hook commands"
grep -q 'secret-host.example.com' <<<"$inv"; check $? 1 "inventory leaks no MCP server URL"
grep -q 'api-token=\*\*\*' <<<"$inv"; check $? 0 "inventory masks token pairs in hook commands"
HOME="$FH" python3 "$REPO/tests/assert_inventory.py" "$S/inventory.py" "$P"; check $? 0 "inventory clips hook commands and calls itself a lower bound"

cmp -s "$REPO/skills/harness-keeper/SKILL.md" "$REPO/skills/harness-audit/assets/templates/harness-keeper-skill.tmpl"; check $? 0 "keeper template matches skills/harness-keeper"
python3 "$REPO/tools/build_dist.py" >/dev/null; check $? 0 "dist packages build and validate"
n=$(python3 -c "import zipfile,sys;print(sum(1 for n in zipfile.ZipFile('$REPO/dist/harness-audit.zip').namelist() if n.split('/')[-1]=='SKILL.md'))"); check "$n" 1 "upload zip has exactly one SKILL.md"
rm -rf "$T"; [ $fail -eq 0 ] && echo "ALL PASSED" || { echo "SOME FAILED"; exit 1; }
