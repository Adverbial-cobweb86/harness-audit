#!/usr/bin/env python3
"""Prove which harness a benchmark environment actually contains, before anything runs there.

The third pilot ran the whole "after" battery in worktrees born from the default branch
instead of the audit commit. All five tasks measured the old harness: a CLAUDE.md of 6,198
lines, no docs/, no scoped rules. ~2.17M tokens spent, no valid measurement, and — worse
than the waste — five confident verdicts that were false, written up as if the new rules
had fired when no rule existed in that tree at all.

Two `git` calls would have caught it. So they are a script, not a sentence in a rubric:
anything that must always happen is a sensor here, and a check that depends on someone
remembering to run it is not ready.

Usage:
  python3 benchenv.py --dir <worktree> --commit <sha>      prove it, exit 1 if it does not hold
  python3 benchenv.py --dir <worktree> --commit <sha> --json

What it proves, in order:
  1. the directory is a git worktree and which commit its HEAD is on;
  2. the audit commit is an ancestor of that HEAD (so the change is present);
  3. observable artefacts of the new state: entry-file line counts, the docs directory,
     the scoped rules on disk. A commit id is a claim; these are the evidence.
  4. that the main tree is clean, which is how a task that "only reads" is caught writing.

Run it before the battery and again after: an environment can change in the middle, and
the proof belongs in the report next to the verdicts.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hlib import docs_root, find_project_root, git, git_ok, load_config, read_text  # noqa: E402

ENTRY = ("CLAUDE.md", "AGENTS.md", "GEMINI.md", "AGENTS.override.md")


def artefacts(d: Path) -> dict:
    """What the directory actually contains, readable without trusting any commit id."""
    cfg = load_config(d)
    docs = docs_root(d, cfg)
    rules = []
    for sub in (".harness/rules", ".claude/rules", ".cursor/rules", ".agents/rules"):
        rules += [str(p.relative_to(d)) for p in sorted((d / sub).glob("*.md*"))]
    return {
        "entry_file_lines": {n: read_text(d / n).count("\n") + 1 for n in ENTRY if (d / n).is_file()},
        "docs_dir": str(cfg.get("docs_dir")),
        "docs_dir_exists": docs.is_dir(),
        "docs_files": len(list(docs.rglob("*.md"))) if docs.is_dir() else 0,
        "scoped_rules": rules,
        "harness_installed": (d / ".harness/config.json").is_file(),
    }


def prove(d: Path, commit: str | None, main: Path | None) -> dict:
    problems = []
    inside = git(d, "rev-parse", "--is-inside-work-tree").strip() == "true"
    if not inside:
        problems.append(f"{d} is not a git worktree: nothing here can be proved")
        return {"dir": str(d), "ok": False, "problems": problems}
    head = git(d, "rev-parse", "HEAD").strip()
    common = git(d, "rev-parse", "--git-common-dir").strip()
    own = git(d, "rev-parse", "--absolute-git-dir").strip()
    isolated = bool(common and own and Path(common).resolve() != Path(own).resolve())
    out = {
        "dir": str(d),
        "head": head,
        "branch": git(d, "rev-parse", "--abbrev-ref", "HEAD").strip(),
        "separate_worktree": isolated,
        "expected_commit": commit,
        "artefacts": artefacts(d),
    }
    if commit:
        resolved = git(d, "rev-parse", "--verify", f"{commit}^{{commit}}").strip()
        if not resolved:
            problems.append(f"commit {commit} does not exist in {d}: the change is not even fetched here")
        else:
            out["expected_commit_resolved"] = resolved
            ok = git_ok(d, "merge-base", "--is-ancestor", resolved, head)
            out["commit_is_ancestor"] = ok
            if not ok:
                problems.append(
                    f"HEAD {head[:12]} does not contain {resolved[:12]}: this environment is NOT the one "
                    "the audit changed. Every number measured here describes the old harness.")
    if main is not None:
        dirty = [l for l in git(main, "status", "--porcelain").splitlines() if l.strip()]
        out["main_tree"] = str(main)
        out["main_tree_clean"] = not dirty
        out["main_tree_changes"] = dirty[:20]
        if dirty:
            problems.append(
                f"the main tree {main} has {len(dirty)} uncommitted change(s): a benchmark task wrote "
                "outside its isolation. 'This task only reads' is a hypothesis about the agent, and the "
                "benchmark exists because that hypothesis is not reliable.")
    # Isolation is reported, never assumed: a task believed to be read-only wrote a
    # migration file straight into the main tree in the third pilot.
    if not isolated:
        problems.append(f"{d} is the main working tree, not an isolated worktree: a task that writes "
                        "will write into the project itself")
    out["ok"] = not problems
    out["problems"] = problems
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="the directory the benchmark task will run in")
    ap.add_argument("--commit", help="the audit commit that must be an ancestor of its HEAD")
    ap.add_argument("--main", help="the project's main working tree, checked for stray writes")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    d = Path(a.dir).expanduser().resolve()
    main_tree = find_project_root(Path(a.main).expanduser()) if a.main else None
    out = prove(d, a.commit, main_tree)
    if a.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"dir:      {out['dir']}")
        print(f"head:     {out.get('head', '-')} ({out.get('branch', '-')})")
        print(f"worktree: {'isolated' if out.get('separate_worktree') else 'MAIN TREE'}")
        if a.commit:
            print(f"contains {a.commit}: {out.get('commit_is_ancestor')}")
        art = out.get("artefacts", {})
        print(f"entry files: {art.get('entry_file_lines')}")
        print(f"docs: {art.get('docs_dir')} exists={art.get('docs_dir_exists')} files={art.get('docs_files')}")
        print(f"scoped rules: {len(art.get('scoped_rules', []))}")
        if "main_tree_clean" in out:
            print(f"main tree clean: {out['main_tree_clean']}")
        for x in out["problems"]:
            print(f"PROBLEM: {x}")
        print("OK: this environment is the one you think it is" if out["ok"]
              else "ABORT: do not launch the benchmark here")
    sys.exit(0 if out["ok"] else 1)


if __name__ == "__main__":
    main()
