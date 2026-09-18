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
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
TPL = SKILL / "assets/templates"
sys.path.insert(0, str(HERE))
from hlib import (AGENTS, DEFAULT_CONFIG, detect_agents, docs_root, find_project_root, git, read_text,  # noqa: E402
                  rel)

SCRIPTS = ["hlib.py", "lint.py", "build_index.py", "sync.py", "hook.py", "inventory.py", "measure.py",
           "transcripts.py", "detect.py", "code_sensor.py", "dirty.py"]
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


def active_git_hooks(root: Path) -> list:
    """Executable hooks the user already has in .git/hooks (samples do not count)."""
    d = root / ".git/hooks"
    if not d.is_dir():
        return []
    return sorted(h.name for h in d.iterdir()
                  if h.is_file() and not h.name.endswith(".sample") and h.stat().st_mode & stat.S_IXUSR)


def hooks_dir(root: Path, plan: Plan) -> Path | None:
    """Where the pre-commit belongs, without breaking a setup that already exists.

    A tracked hooks folder is the point: a hook in .git/hooks lives on one machine
    only, so a clone gets nothing. But core.hooksPath is local git config, and
    setting it silently disables whatever the user already had. So: honour an
    existing core.hooksPath (husky and friends), refuse to touch untracked hooks
    that are already active, and only then default to .githooks.
    """
    configured = git(root, "config", "--local", "--get", "core.hooksPath").strip()
    if configured:
        plan.actions.append(f"note   core.hooksPath is already {configured}: installing there, not changing it")
        return (root / configured) if not Path(configured).is_absolute() else Path(configured)
    existing = active_git_hooks(root)
    if existing:
        plan.actions.append(
            "SKIP   pre-commit: .git/hooks already has active hook(s) (" + ", ".join(existing) + "). "
            "Setting core.hooksPath would disable them. Move them to .githooks yourself, then rerun with "
            "--hooks-path .githooks, or install the hook manually.")
        return None
    return root / ".githooks"


def precommit(root: Path, plan: Plan, forced: str | None, sensor: bool):
    if not (root / ".git").is_dir():
        plan.actions.append("skip   pre-commit (not a git repo)")
        return None
    target = (root / forced) if forced else hooks_dir(root, plan)
    if target is None:
        return None
    p = target / "pre-commit"
    lines = ["python3 .harness/scripts/sync.py --check && python3 .harness/scripts/lint.py --staged || "
             "{ echo 'harness lint failed'; exit 1; }"]
    if sensor:
        # Only exit 1 means a file got worse. Exit 2 means the sensor is not configured
        # any more, which is a reason to say nothing, not a reason to block the commit.
        lines.append("python3 .harness/scripts/code_sensor.py --staged; "
                     "if [ $? -eq 1 ]; then echo 'code sensor: a file got worse'; exit 1; fi")
    block = "\n# >>> harness-audit\n" + "\n".join(lines) + "\n# <<< harness-audit\n"
    current = read_text(p) if p.exists() else "#!/bin/sh\n"
    if "harness-audit" in current:
        plan.actions.append(f"same   {rel(root, p)}")
    else:
        plan.write(p, current.rstrip("\n") + "\n" + block)
        if plan.apply:
            p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return target


def activate_hooks_path(root: Path, plan: Plan, target: Path):
    """Point git at the tracked folder. Only reached when nothing was there before."""
    value = rel(root, target)
    if git(root, "config", "--local", "--get", "core.hooksPath").strip() == value:
        plan.actions.append(f"same   core.hooksPath={value}")
        return
    plan.actions.append(f"config core.hooksPath={value}")
    if plan.apply:
        git(root, "config", "core.hooksPath", value)


def npm_prepare(root: Path, plan: Plan, target: Path):
    """A clone runs `npm install`, which runs `prepare`, which arms the hooks."""
    p = root / "package.json"
    if not p.is_file():
        return
    try:
        data = json.loads(read_text(p))
    except ValueError:
        plan.actions.append("skip   package.json (not valid JSON)")
        return
    wanted = f"git config core.hooksPath {rel(root, target)} || true"
    scripts = data.setdefault("scripts", {})
    cur = scripts.get("prepare", "")
    if wanted in cur:
        plan.actions.append("same   package.json prepare")
        return
    scripts["prepare"] = f"{cur} && {wanted}" if cur.strip() else wanted
    plan.write(p, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def measured_budgets(root: Path, cfg: dict) -> dict:
    """Set the initial budgets from what the project is today, not from a target.

    A gate installed with the default budget over a legacy harness is red on its first
    run: in the second pilot it blocked the very commits that were shrinking a 13k-line
    CLAUDE.md. So the opening budget is a photograph of the current state (never looser
    than the target), it is marked transitional, and the ratchet is what brings it down
    — the same rule the code sensor follows.
    """
    import inventory
    inv = inventory.build(root, include_user=False)
    measured_tokens = max([d["always_on_est_tokens"] for d in inv["agents"].values()] or [0])
    measured_lines = 0
    for name in ("CLAUDE.md", "AGENTS.md", "GEMINI.md", "AGENTS.override.md"):
        text = read_text(root / name) if (root / name).is_file() else ""
        if text:
            measured_lines = max(measured_lines, text.count("\n") + 1)
    targets = {"always_on_tokens": int(DEFAULT_CONFIG["budgets"]["always_on_tokens"]),
               "entry_file_lines": int(DEFAULT_CONFIG["budgets"]["entry_file_lines"])}
    opening = {"always_on_tokens": max(measured_tokens, targets["always_on_tokens"]),
               "entry_file_lines": max(measured_lines, targets["entry_file_lines"])}
    cfg["budgets"].update(opening)
    if opening != targets:
        cfg["budgets_transitional"] = {"measured_on": date.today().isoformat(), "opening": opening,
                                       "targets": targets}
    else:
        cfg.pop("budgets_transitional", None)
    return opening


def budget_note(opening: dict) -> str:
    return (f"Opening budgets measured from this project: {opening['always_on_tokens']} always-on tokens, "
            f"{opening['entry_file_lines']} entry-file lines. Marked transitional; lint warns (H019) until "
            f"'lint.py --update-lock' tightens them to the real values.")


def detect_lint_command(root: Path) -> dict | None:
    """The sensor runs the project's own linter. No linter, no sensor."""
    p = root / "package.json"
    if not p.is_file():
        return None
    try:
        data = json.loads(read_text(p))
    except ValueError:
        return None
    deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
    if not any(k == "eslint" or k.startswith("eslint") for k in deps) and "lint" not in (data.get("scripts") or {}):
        return None
    return {"command": "npx eslint . --format json", "format": "eslint-json",
            "baseline": ".harness/eslint-baseline.json"}


def entry_blocks(root: Path, plan: Plan, agents: list, idx: str, hooks: Path | None):
    """AGENTS.md is canonical. CLAUDE.md imports it. GEMINI.md never repeats it."""
    block = read_text(TPL / "entry-block.md").replace("{{INDEX}}", idx)
    if hooks is None:
        block = "\n".join(l for l in block.splitlines() if "{{HOOKS}}" not in l)
    else:
        block = block.replace("{{HOOKS}}", rel(root, hooks))
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
    ap.add_argument("--hooks-path", help="install the pre-commit here instead of the detected folder "
                                         "(default: .githooks, tracked by git)")
    ap.add_argument("--lint-command", help="command the code sensor runs (default: detected from package.json)")
    ap.add_argument("--lint-format", choices=["eslint-json", "text"], default=None)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    root = find_project_root(Path(a.project))
    plan = Plan(root, a.apply)
    agents = "auto" if a.agents == "auto" else [x.strip() for x in a.agents.split(",") if x.strip() in AGENTS]

    cfg_path = root / ".harness/config.json"
    cfg = json.loads(read_text(cfg_path)) if cfg_path.exists() else json.loads(json.dumps(DEFAULT_CONFIG))
    cfg["agents"], cfg["docs_dir"], cfg["language"] = agents, a.docs_dir, a.language
    sensor = ({"command": a.lint_command, "format": a.lint_format or "text",
               "baseline": ".harness/code-baseline.json"} if a.lint_command
              else cfg.get("code_sensor") or detect_lint_command(root))
    if sensor:
        cfg["code_sensor"] = sensor
    else:
        cfg.pop("code_sensor", None)
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
    hooks_target = None
    if a.with_precommit:
        hooks_target = precommit(root, plan, a.hooks_path, bool(sensor))
        if hooks_target is not None and hooks_target != root / ".git/hooks":
            activate_hooks_path(root, plan, hooks_target)
            npm_prepare(root, plan, hooks_target)
    if a.with_ci:
        plan.copy(TPL / "ci/harness.yml", root / ".github/workflows/harness.yml")
    if a.entry_blocks:
        idx = rel(root, droot / cfg["index"].get("file", "index.md"))
        entry_blocks(root, plan, enabled, idx, hooks_target)

    if not a.apply:  # dry run: nothing was written, so this is the best estimate available
        opening = measured_budgets(root, cfg)
        plan.actions.append(budget_note(opening))
    if not sensor:
        plan.actions.append("note   no lint command found: code sensor not installed. "
                            "Record it as a gap in the report (a project with no code sensor has no ratchet).")

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
        # Measured last, on purpose: install writes the routing block into the entry files
        # and sync projects rules into them, so a budget read any earlier gates a smaller
        # project than the one that now exists.
        opening = measured_budgets(root, cfg)
        cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("\nSynced projections and generated the index.")
        if cfg.get("budgets_transitional"):
            print(budget_note(opening))
        print("Next: move content per the approved plan, then python3 .harness/scripts/lint.py")
        if hooks_target is not None and hooks_target != root / ".git/hooks":
            print(f"Hooks are tracked in {rel(root, hooks_target)}. A collaborator arms them with "
                  f"'git config core.hooksPath {rel(root, hooks_target)}' (npm projects get it from 'npm install').")
        if sensor:
            print(f"Code sensor: {sensor['command']} -> {sensor['baseline']}. "
                  "Run python3 .harness/scripts/code_sensor.py once and commit the baseline.")
        if "codex" in enabled:
            print("Codex: run /hooks inside Codex to trust the project hooks (or copy them to ~/.codex/hooks.json).")
        if "antigravity" in enabled:
            print("Antigravity: hook schema varies by agy version. Review .agents/hooks.harness.example.json, "
                  "adapt, rename to .agents/hooks.json, verify with 'agy inspect'. Pre-commit remains the guaranteed gate.")
        if external_vault:
            print("Vault outside the repo: Codex needs --add-dir <vault>, Cursor needs the vault in a multi-root workspace.")


if __name__ == "__main__":
    main()
