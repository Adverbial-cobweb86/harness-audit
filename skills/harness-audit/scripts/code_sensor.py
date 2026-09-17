#!/usr/bin/env python3
"""Per-file ratchet over a project's own linter. Fails only when a file gets worse.

A binary gate is unusable on a codebase that already has problems: the first pilot
had 57 pre-existing ESLint errors, so "zero errors" would have blocked every commit
and been switched off within a day. Instead we record how many problems each file
has today and fail only when a file goes above its own line. Improvements are reported
but never written back on their own: moving the line is a deliberate act
(--update-baseline), because the baseline is a tracked generated file and silently
rewriting it on every commit that fixes something is a standing merge conflict.

  python3 code_sensor.py [--project PATH] [--update-baseline] [--staged]

The command and output format come from .harness/config.json:

  "code_sensor": {"command": "npx eslint . --format json", "format": "eslint-json",
                  "baseline": ".harness/eslint-baseline.json"}

format is "eslint-json" (an ESLint JSON report) or "text" (any tool that prints one
problem per line as path:line:col: message or path(line,col): message). Nothing here
is ESLint-specific beyond that default.
Exit: 0 ok or baseline created, 1 a file got worse, 2 sensor misconfigured.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from hlib import changed_files, find_project_root, load_config, read_text, rel  # noqa: E402

DEFAULT_BASELINE = ".harness/code-baseline.json"
TEXT_RE = re.compile(r"^\s*([^\s:(][^:(]*\.[A-Za-z0-9]+)[:(](\d+)")


def config(root: Path) -> dict:
    return load_config(root).get("code_sensor") or {}


def parse_eslint_json(out: str, root: Path) -> dict:
    try:
        data = json.loads(out or "[]")
    except ValueError:
        return {}
    counts = {}
    for f in data if isinstance(data, list) else []:
        path = f.get("filePath")
        if not path:
            continue
        n = int(f.get("errorCount", 0)) + int(f.get("warningCount", 0))
        if n:
            counts[rel(root, Path(path))] = n
    return counts


def parse_text(out: str, root: Path) -> dict:
    counts = {}
    for line in (out or "").splitlines():
        m = TEXT_RE.match(line)
        if not m:
            continue
        p = Path(m.group(1))
        key = rel(root, p if p.is_absolute() else root / p)
        counts[key] = counts.get(key, 0) + 1
    return counts


def run(root: Path, cfg: dict):
    proc = subprocess.run(cfg["command"], shell=True, cwd=str(root), capture_output=True, text=True)
    out = proc.stdout + ("" if cfg.get("format") == "eslint-json" else "\n" + proc.stderr)
    fmt = cfg.get("format", "text")
    return parse_eslint_json(proc.stdout, root) if fmt == "eslint-json" else parse_text(out, root)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=".")
    ap.add_argument("--update-baseline", action="store_true", help="accept current counts as the new line")
    ap.add_argument("--staged", action="store_true", help="only judge files staged for commit")
    a = ap.parse_args()
    root = find_project_root(Path(a.project))
    cfg = config(root)
    if not cfg.get("command"):
        print("code_sensor: no command in .harness/config.json -> code_sensor.command; nothing to check.")
        return 2

    counts = run(root, cfg)
    bpath = root / cfg.get("baseline", DEFAULT_BASELINE)
    fresh = not bpath.exists()
    base = {} if fresh else (json.loads(read_text(bpath) or "{}") or {})
    scope = set(changed_files(root, staged_only=True)) if a.staged else None

    worse = [(f, base.get(f, 0), n) for f, n in sorted(counts.items())
             if n > base.get(f, 0) and (scope is None or f in scope)]

    if fresh or a.update_baseline:
        bpath.parent.mkdir(parents=True, exist_ok=True)
        bpath.write_text(json.dumps(counts, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"code_sensor: baseline {'created' if fresh else 'updated'} at {rel(root, bpath)} "
              f"({sum(counts.values())} problem(s) in {len(counts)} file(s)). Commit it.")
        return 0

    if worse:
        print("code_sensor: these files got worse than their baseline:")
        for f, was, now in worse:
            print(f"  {f}: {was} -> {now}")
        print("Fix them, or run: python3 .harness/scripts/code_sensor.py --update-baseline "
              "(and say in the commit why the line moved up).")
        return 1

    gone = sum(base.get(f, 0) - counts.get(f, 0) for f in base if counts.get(f, 0) < base.get(f, 0))
    if gone:
        # Tightening the line is the user's call, never a side effect of a commit that
        # happened to fix something: the baseline is a generated file, and rewriting it
        # behind people's backs turns every improvement into a merge conflict for the team.
        print(f"code_sensor: ok, {gone} problem(s) fewer than the baseline. "
              f"Consolidate when you want to with: python3 .harness/scripts/code_sensor.py --update-baseline")
        return 0
    print(f"code_sensor: ok, no file above its baseline ({sum(counts.values())} known problem(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
