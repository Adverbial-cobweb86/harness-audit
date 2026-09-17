#!/usr/bin/env python3
"""One source of truth, many agents.

Canonical sources live in .harness/:
  .harness/rules/<area>.md      frontmatter: description, paths (list of globs)
  .harness/skills/<name>/       standard Agent Skill folder

Projections (generated, never edited by hand):
  claude-code  .claude/rules/<area>.md (paths)      .claude/skills/<name>/
  cursor       .cursor/rules/<area>.mdc (globs)     .cursor/skills/<name>/
  codex        routing block in AGENTS.md           .agents/skills/<name>/
  antigravity  routing block in AGENTS.md/GEMINI.md .agents/skills/<name>/

Usage: python3 sync.py [--project PATH] [--check]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

from hlib import GENERATED_MARK, as_list, enabled_agents, find_project_root, index_path, load_config, parse_frontmatter, read_text, rel

R_START, R_END = "<!-- harness:routes:start -->", "<!-- harness:routes:end -->"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(path.rglob("*")) if path.is_dir() else [path]:
        if p.is_file():
            h.update(p.relative_to(path if path.is_dir() else path.parent).as_posix().encode())
            h.update(p.read_bytes())
    return h.hexdigest()[:16]


def rule_sources(root: Path, cfg: dict):
    src = root / cfg.get("rules_source", ".harness/rules")
    if not src.is_dir():
        return []
    return [r for r in sorted(src.glob("*.md")) if r.name.lower() != "readme.md" and not r.name.startswith("_")]


def rule_projections(root: Path, cfg: dict, agents: list):
    out = {}
    for r in rule_sources(root, cfg):
        fm, body = parse_frontmatter(read_text(r))
        paths, desc = as_list(fm.get("paths")), str(fm.get("description", r.stem))
        mark = f"{GENERATED_MARK} from {rel(root, r)}. Edit the source, then run sync.py -->\n"
        if "claude-code" in agents:
            head = "---\n" + (("paths:\n" + "".join(f'  - "{p}"\n' for p in paths)) if paths else "") + "---\n"
            out[root / ".claude/rules" / r.name] = head + mark + body.lstrip("\n")
        if "cursor" in agents:
            head = (f"---\ndescription: {desc}\nglobs: {', '.join(paths)}\n"
                    f"alwaysApply: false\n---\n")
            out[root / ".cursor/rules" / (r.stem + ".mdc")] = head + mark + body.lstrip("\n")
    return out


def routes_block(root: Path, cfg: dict) -> str:
    lines = [R_START, "| When you work on | Read first |", "|---|---|"]
    for r in rule_sources(root, cfg):
        fm, _ = parse_frontmatter(read_text(r))
        scope = ", ".join(f"`{p}`" for p in as_list(fm.get("paths"))) or str(fm.get("description", r.stem))
        lines.append(f"| {scope} | `{rel(root, r)}` |")
    lines.append(f"| anything else | `{rel(root, index_path(root, cfg))}` (catalog of all docs) |")
    lines.append(R_END)
    return "\n".join(lines)


def skill_targets(root: Path, agents: list):
    t = []
    if "claude-code" in agents:
        t.append(root / ".claude/skills")
    if "cursor" in agents:
        t.append(root / ".cursor/skills")
    if "codex" in agents or "antigravity" in agents:
        t.append(root / ".agents/skills")
    return t


def run(root: Path, check: bool) -> list:
    cfg = load_config(root)
    agents = enabled_agents(root, cfg)
    problems = []
    manifest_path = root / ".harness/generated.json"
    manifest = {}
    old_manifest = json.loads(read_text(manifest_path) or "{}") if manifest_path.exists() else {}
    # rules
    projections = rule_projections(root, cfg, agents)
    for folder, pattern in ((".claude/rules", "*.md"), (".cursor/rules", "*.mdc")):
        for gen in (root / folder).glob(pattern):
            if GENERATED_MARK in read_text(gen) and gen not in projections:
                if check:
                    problems.append(f"stale generated file: {rel(root, gen)}")
                else:
                    gen.unlink()
    for path, content in projections.items():
        manifest[rel(root, path)] = "rule"
        if read_text(path) != content:
            if check:
                problems.append(f"out of sync: {rel(root, path)}")
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
    # routing blocks in entry files that opted in with markers
    block = routes_block(root, cfg)
    for name in ("AGENTS.md", "GEMINI.md", "CLAUDE.md"):
        p = root / name
        text = read_text(p) if p.exists() else ""
        if R_START in text and R_END in text:
            new = text.split(R_START)[0] + block + text.split(R_END, 1)[1]
            if new != text:
                if check:
                    problems.append(f"routing table out of sync: {name}")
                else:
                    p.write_text(new, encoding="utf-8")
    # skills
    ssrc = root / cfg.get("skills_source", ".harness/skills")
    for sk in sorted(ssrc.iterdir()) if ssrc.is_dir() else []:
        if not (sk / "SKILL.md").is_file():
            continue
        for tdir in skill_targets(root, agents):
            dest = tdir / sk.name
            manifest[rel(root, dest)] = "skill"
            if not dest.exists() or digest(dest) != digest(sk):
                if check:
                    problems.append(f"out of sync: {rel(root, dest)}")
                else:
                    if dest.exists():
                        shutil.rmtree(dest)
                    shutil.copytree(sk, dest)
    for old, kind in old_manifest.items():
        if kind == "skill" and old not in manifest and (root / old).is_dir():
            if check:
                problems.append(f"stale generated skill: {old}")
            else:
                shutil.rmtree(root / old)
    if not check:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=".")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    root = find_project_root(Path(a.project))
    problems = run(root, a.check)
    for p in problems:
        print(p, file=sys.stderr)
    if a.check and problems:
        sys.exit(1)
    print("in sync" if a.check else "sync complete")


if __name__ == "__main__":
    main()
