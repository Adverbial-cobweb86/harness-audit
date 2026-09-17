#!/usr/bin/env python3
"""Build distributable packages.

  python3 tools/build_dist.py            -> dist/

Outputs:
  dist/harness-audit.zip         upload-ready (Claude apps, Skills API, gh skill): one SKILL.md, standard frontmatter
  dist/harness-keeper.zip        upload-ready, optional standalone install
  dist/claude-code/<skill>/      filesystem install for Claude Code (~/.claude/skills), keeps Claude Code extensions
  dist/harness-audit-repo.zip    full repository for GitHub

Upload validators accept exactly one SKILL.md per package and only the Agent Skills
standard frontmatter keys. Claude Code extensions (disable-model-invocation, argument-hint)
are stripped from upload packages and kept in the Claude Code filesystem copy.
"""
from __future__ import annotations

import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
SKILLS = ["harness-audit", "harness-keeper"]
STANDARD_KEYS = {"name", "description", "license", "allowed-tools", "metadata", "compatibility"}
EXCLUDE = {"__pycache__", ".DS_Store", "evals", "node_modules"}


def strip_frontmatter(text: str) -> str:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        raise SystemExit("SKILL.md without frontmatter")
    kept, skip = [], False
    for line in m.group(1).splitlines():
        top = re.match(r"^([A-Za-z0-9_\-]+)\s*:", line)
        if top:
            skip = top.group(1) not in STANDARD_KEYS
        if not skip:
            kept.append(line)
    return "---\n" + "\n".join(kept) + "\n---\n" + text[m.end():]


def validate(folder: Path):
    found = [p for p in folder.rglob("SKILL.md") if not set(p.relative_to(folder).parts) & EXCLUDE]
    if len(found) != 1 or found[0] != folder / "SKILL.md":
        raise SystemExit(f"{folder.name}: expected exactly one SKILL.md at root, found {[str(p) for p in found]}")
    fm = re.match(r"^---\n(.*?)\n---", (folder / "SKILL.md").read_text(), re.S).group(1)
    keys = {k for k in re.findall(r"^([A-Za-z0-9_\-]+)\s*:", fm, re.M)}
    if keys - STANDARD_KEYS:
        raise SystemExit(f"{folder.name}: non-standard keys {keys - STANDARD_KEYS}")
    name = re.search(r"^name:\s*(.+)$", fm, re.M).group(1).strip()
    desc = re.search(r"^description:\s*(.+)$", fm, re.M).group(1).strip()
    if name != folder.name or not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) or len(name) > 64:
        raise SystemExit(f"{folder.name}: invalid name '{name}'")
    if len(desc) > 1024 or "<" in desc or ">" in desc:
        raise SystemExit(f"{folder.name}: description too long or contains angle brackets")


def zip_dir(src: Path, out: Path, arc_base: Path):
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(src.rglob("*")):
            rel = p.relative_to(arc_base)
            if p.is_file() and not set(rel.parts) & EXCLUDE:
                z.write(p, rel.as_posix())


def main():
    if DIST.exists():
        shutil.rmtree(DIST)
    (DIST / "upload").mkdir(parents=True)
    for s in SKILLS:
        src = ROOT / "skills" / s
        # Claude Code filesystem copy (extensions kept)
        shutil.copytree(src, DIST / "claude-code" / s, ignore=shutil.ignore_patterns(*EXCLUDE))
        # upload copy (standard frontmatter only)
        up = DIST / "upload" / s
        shutil.copytree(src, up, ignore=shutil.ignore_patterns(*EXCLUDE))
        (up / "SKILL.md").write_text(strip_frontmatter((up / "SKILL.md").read_text()))
        validate(up)
        zip_dir(up, DIST / f"{s}.zip", up.parent)
        print(f"ok  dist/{s}.zip")
    with zipfile.ZipFile(DIST / "harness-audit-repo.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(ROOT.rglob("*")):
            rel = p.relative_to(ROOT)
            if p.is_file() and rel.parts[0] not in ("dist", ".git") and not set(rel.parts) & {"__pycache__", ".DS_Store"}:
                z.write(p, ("harness-audit/" + rel.as_posix()))
    print("ok  dist/harness-audit-repo.zip")


if __name__ == "__main__":
    sys.exit(main())
