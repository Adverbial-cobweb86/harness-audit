#!/usr/bin/env python3
"""Install the maintenance layer into a project. Dry-run by default; --apply writes.

  python3 install.py --project . --agents claude-code,codex,cursor,antigravity \
      [--docs-dir docs | --docs-dir ~/Vault/Projects/X] [--vault-path ~/Vault] [--vault-topology external] \
      [--entry-blocks] [--with-precommit] [--with-ci] --apply

Writes:
  .harness/config.json, PLACEMENT.md, scripts/, skills/harness-keeper/, rules/, reports/
  docs index + log (in docs dir or vault folder)
  hooks: .claude/settings.json | .cursor/hooks.json | .codex/hooks.json | .agents/hooks.harness.json (experimental)
  optional: git pre-commit, GitHub Actions workflow, routing block in AGENTS.md/CLAUDE.md/GEMINI.md
Never deletes. Existing hook entries are preserved; ours are added once (idempotent).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import stat
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
TPL = SKILL / "assets/templates"
sys.path.insert(0, str(HERE))
from hlib import AGENTS, DEFAULT_CONFIG, detect_agents, docs_root, find_project_root, read_text, rel  # noqa: E402

SCRIPTS = ["hlib.py", "lint.py", "build_index.py", "sync.py", "hook.py", "inventory.py", "measure.py",
           "transcripts.py", "detect.py"]
MARK = "harness/scripts/hook.py"


class Plan:
    def __init__(self, root: Path, apply: bool):
        self.root, self.apply, self.actions = root, apply, []

    def write(self, path: Path, content: str, overwrite=True):
        exists = path.exists()
        if exists and not overwrite:
            self.actions.append(f"keep   {rel(self.root, path)} (exists)")
            return
        if exists and read_text(path) == content:
            self.actions.append(f"same   {rel(self.root, path)}")
            return
        self.actions.append(f"{'update' if exists else 'create'} {rel(self.root, path)}")
        if self.apply:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    def copy(self, src: Path, dest: Path):
        self.write(dest, read_text(src))


def cmd(agent, event):
    return f"python3 .harness/scripts/hook.py --agent {agent} --event {event}"


def merge_claude(root: Path, plan: Plan, vault: str | None):
    p = root / ".claude/settings.json"
    data = json.loads(read_text(p) or "{}") if p.exists() else {}
    hooks = data.setdefault("hooks", {})
    base = 'python3 "$CLAUDE_PROJECT_DIR"/.harness/scripts/hook.py --agent claude-code --event '
    wanted = {"PostToolUse": ("Write|Edit|MultiEdit|NotebookEdit", "post-edit"), "Stop": (None, "stop"),
              "SessionStart": ("startup|resume|clear|compact", "session-start")}
    for ev, (matcher, name) in wanted.items():
        groups = hooks.setdefault(ev, [])
        if any(MARK in h.get("command", "") for g in groups for h in g.get("hooks", [])):
            continue
        g = {"hooks": [{"type": "command", "command": base + name, "timeout": 60}]}
        if matcher:
            g = {"matcher": matcher, **g}
        groups.append(g)
    if vault:
        dirs = data.setdefault("permissions", {}).setdefault("additionalDirectories", [])
        if vault not in dirs:
            dirs.append(vault)
    plan.write(p, json.dumps(data, indent=2) + "\n")


def merge_cursor(root: Path, plan: Plan):
    p = root / ".cursor/hooks.json"
    data = json.loads(read_text(p) or "{}") if p.exists() else {}
    data.setdefault("version", 1)
    hooks = data.setdefault("hooks", {})
    for ev, name in (("afterFileEdit", "post-edit"), ("stop", "stop"), ("sessionStart", "session-start")):
        lst = hooks.setdefault(ev, [])
        if not any(MARK in h.get("command", "") for h in lst):
            lst.append({"command": cmd("cursor", name)})
    plan.write(p, json.dumps(data, indent=2) + "\n")


def merge_codex(root: Path, plan: Plan):
    p = root / ".codex/hooks.json"
    data = json.loads(read_text(p) or "{}") if p.exists() else {}
    hooks = data.setdefault("hooks", {})
    wanted = {"PostToolUse": ("apply_patch|Edit|Write", "post-edit"), "Stop": (None, "stop"),
              "SessionStart": ("startup|resume|clear", "session-start")}
    for ev, (matcher, name) in wanted.items():
        groups = hooks.setdefault(ev, [])
        if any(MARK in h.get("command", "") for g in groups for h in g.get("hooks", [])):
            continue
        g = {"hooks": [{"type": "command", "command": cmd("codex", name), "timeout": 60}]}
        if matcher:
            g = {"matcher": matcher, **g}
        groups.append(g)
    plan.write(p, json.dumps(data, indent=2) + "\n")


def antigravity_example(root: Path, plan: Plan):
    plan.copy(TPL / "hooks/antigravity.hooks.example.json", root / ".agents/hooks.harness.example.json")


def precommit(root: Path, plan: Plan):
    p = root / ".git/hooks/pre-commit"
    if not (root / ".git").is_dir():
        plan.actions.append("skip   pre-commit (not a git repo)")
        return
    block = ("\n# >>> harness-audit\npython3 .harness/scripts/sync.py --check && "
             "python3 .harness/scripts/lint.py --staged || { echo 'harness lint failed'; exit 1; }\n# <<< harness-audit\n")
    current = read_text(p) if p.exists() else "#!/bin/sh\n"
    if "harness-audit" in current:
        plan.actions.append("same   .git/hooks/pre-commit")
        return
    plan.write(p, current.rstrip("\n") + "\n" + block)
    if plan.apply:
        p.chmod(p.stat().st_mode | stat.S_IEXEC)


def entry_blocks(root: Path, plan: Plan, agents: list, idx: str):
    """AGENTS.md is canonical. CLAUDE.md imports it. GEMINI.md never repeats it."""
    block = read_text(TPL / "entry-block.md").replace("{{INDEX}}", idx)
    use_agents_md = bool({"codex", "cursor", "antigravity"} & set(agents)) or (root / "AGENTS.md").exists()
    canonical = root / ("AGENTS.md" if use_agents_md else "CLAUDE.md")
    text = read_text(canonical) if canonical.exists() else ""
    if "harness:routes:start" in text:
        plan.actions.append(f"same   {canonical.name} (routing block present)")
    else:
        plan.write(canonical, (text.rstrip("\n") + "\n\n" if text else "") + block)
    if use_agents_md and "claude-code" in agents:
        cp = root / "CLAUDE.md"
        ctext = read_text(cp) if cp.exists() else ""
        if not re.search(r"^@AGENTS\.md\s*$", ctext, re.M):
            plan.write(cp, "@AGENTS.md\n\n" + ctext)
        if "harness:routes:start" in ctext:
            plan.actions.append("note   CLAUDE.md also has a routing block: remove it, AGENTS.md is canonical")
    if use_agents_md and (root / "GEMINI.md").exists():
        plan.actions.append("note   GEMINI.md: Antigravity also reads AGENTS.md; keep only Antigravity-specific lines in GEMINI.md")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=".")
    ap.add_argument("--agents", default="auto")
    ap.add_argument("--docs-dir", default="docs")
    ap.add_argument("--vault-path")
    ap.add_argument("--vault-topology", choices=["inside-repo", "repo-inside-vault", "external"])
    ap.add_argument("--language", default="auto")
    ap.add_argument("--entry-blocks", action="store_true")
    ap.add_argument("--with-precommit", action="store_true")
    ap.add_argument("--with-ci", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    root = find_project_root(Path(a.project))
    plan = Plan(root, a.apply)
    agents = "auto" if a.agents == "auto" else [x.strip() for x in a.agents.split(",") if x.strip() in AGENTS]

    cfg_path = root / ".harness/config.json"
    cfg = json.loads(read_text(cfg_path)) if cfg_path.exists() else json.loads(json.dumps(DEFAULT_CONFIG))
    cfg["agents"], cfg["docs_dir"], cfg["language"] = agents, a.docs_dir, a.language
    if a.vault_path:
        cfg["vault"] = {"enabled": True, "path": a.vault_path, "topology": a.vault_topology}
    plan.write(cfg_path, json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")

    for s in SCRIPTS:
        plan.copy(HERE / s, root / ".harness/scripts" / s)
    plan.copy(TPL / "PLACEMENT.md", root / ".harness/PLACEMENT.md")
    plan.copy(TPL / "harness-keeper-skill.tmpl", root / ".harness/skills/harness-keeper/SKILL.md")
    plan.write(root / ".harness/rules/README.md", read_text(TPL / "rules-README.md"), overwrite=False)
    plan.write(root / ".harness/.gitignore", "state/\n", overwrite=False)

    droot = docs_root(root, cfg)
    plan.write(droot / cfg["log"].get("file", "log.md"), read_text(TPL / "log.md"), overwrite=False)
    enabled = agents if agents != "auto" else detect_agents(root)
    external_vault = a.vault_path if a.vault_topology == "external" else None
    if "claude-code" in enabled:
        merge_claude(root, plan, str(Path(a.docs_dir).expanduser()) if external_vault else None)
    if "cursor" in enabled:
        merge_cursor(root, plan)
    if "codex" in enabled:
        merge_codex(root, plan)
    if "antigravity" in enabled:
        antigravity_example(root, plan)
    if a.with_precommit:
        precommit(root, plan)
    if a.with_ci:
        plan.copy(TPL / "ci/harness.yml", root / ".github/workflows/harness.yml")
    if a.entry_blocks:
        idx = rel(root, droot / cfg["index"].get("file", "index.md"))
        entry_blocks(root, plan, enabled, idx)

    print(("APPLIED" if a.apply else "DRY RUN (use --apply to write)") + f" in {root}")
    print("\n".join("  " + x for x in plan.actions))
    if a.apply:
        import build_index
        import sync
        sync.run(root, check=False)
        ipath = docs_root(root, cfg) / cfg["index"].get("file", "index.md")
        current = read_text(ipath) if ipath.exists() else ""
        ipath.parent.mkdir(parents=True, exist_ok=True)
        ipath.write_text(build_index.merged(current, build_index.render(root, cfg)) + "\n", encoding="utf-8")
        print("\nSynced projections and generated the index.")
        print("Next: move content per the approved plan, then python3 .harness/scripts/lint.py")
        if "codex" in enabled:
            print("Codex: run /hooks inside Codex to trust the project hooks (or copy them to ~/.codex/hooks.json).")
        if "antigravity" in enabled:
            print("Antigravity: hook schema varies by agy version. Review .agents/hooks.harness.example.json, "
                  "adapt, rename to .agents/hooks.json, verify with 'agy inspect'. Pre-commit remains the guaranteed gate.")
        if external_vault:
            print("Vault outside the repo: Codex needs --add-dir <vault>, Cursor needs the vault in a multi-root workspace.")


if __name__ == "__main__":
    main()
