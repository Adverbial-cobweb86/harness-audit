#!/usr/bin/env python3
"""Read-only survey of an unclean working tree, so the user decides with evidence.

In both pilots what sat uncommitted was real work: a submodule pointer carrying a whole
release of another repository, tag included, and a month-old stash that took a line-by-line
comparison to prove redundant. Both times the agent investigated on its own initiative.
"Commit or stash first" without that survey asks the user to decide blind.

  python3 dirty.py [--project PATH]

This module NEVER writes: no stash, checkout, clean, reset, add or commit, and no .gitignore
edit. It runs read-only git commands through hlib.git (the real binary) and returns facts.
It also never copies file content into the report: the report lands in .harness/reports/,
which is versioned and shared, and the working tree it describes is someone's unfinished
work. Paths, sizes, line counts and dates only; user-written text (a stash subject, a
submodule commit message) is clipped and passed through the secret mask.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from hlib import dump_json, find_project_root, git, mask_secrets, safe_command  # noqa: E402

# Directory and file names that mean "build output or installed dependency", not work.
CACHE_NAMES = {
    "node_modules", ".next", ".nuxt", ".svelte-kit", ".pnpm-store", ".yarn", ".turbo", ".parcel-cache",
    "dist", "build", "out", "target", "coverage", ".coverage", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".venv", "venv", ".gradle", ".tox", "vendor", ".terraform",
}
CACHE_SUFFIXES = (".pyc", ".pyo", ".log", ".tsbuildinfo")
MAX_ITEMS = 20          # per category; the rest is reported as a count
# Past this, stop describing items one by one: the survey runs on every --git-only call,
# including apply's step 0. Overridable so the degraded path can be exercised.
SLOW_SECONDS = float(os.environ.get("HARNESS_DIRTY_SLOW_SECONDS", "2.0"))
SUBJECT_CHARS = 80


def safe_text(text: str) -> str:
    """User-written text (stash subject, commit message): clipped and masked."""
    return safe_command(text, SUBJECT_CHARS)


def safe_path(rel_path: str) -> str:
    """A path is data too: a filename can carry a credential (an exported .env, a dumped token),
    and this report is versioned."""
    return mask_secrets(rel_path)


def is_cache(rel_path: str) -> bool:
    parts = Path(rel_path).parts
    return any(p in CACHE_NAMES for p in parts) or rel_path.endswith(CACHE_SUFFIXES)


def cache_root(rel_path: str) -> str:
    parts = Path(rel_path).parts
    for i, p in enumerate(parts):
        if p in CACHE_NAMES:
            return "/".join(parts[:i + 1]) + "/"
    return rel_path


def stat_of(root: Path, rel_path: str):
    p = root / rel_path
    try:
        st = p.stat()
        return st.st_size, int((time.time() - st.st_mtime) // 86400)
    except OSError:
        return 0, None


def dir_totals(root: Path, rel_dir: str):
    files = size = 0
    for p in (root / rel_dir).rglob("*"):
        try:
            if p.is_file():
                files += 1
                size += p.stat().st_size
        except OSError:
            continue
    return files, size


def human(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} GB"


def parse_status(root: Path):
    """One status call feeds every category: a second pass over a large tree is wasted time."""
    modified, untracked, submodules = [], [], []
    for line in git(root, "status", "--porcelain", "--untracked-files=all").splitlines():
        if len(line) < 4:
            continue
        code, path = line[:2], line[3:].split(" -> ")[-1].strip().strip('"')
        if code == "??":
            untracked.append(path)
        elif code.strip():
            (submodules if (root / path).is_dir() else modified).append((code, path))
    return modified, untracked, submodules


def numstat_map(root: Path, *args):
    out = {}
    for line in git(root, "diff", "--numstat", *args).splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            added, removed, path = parts
            a, r = (0 if added == "-" else int(added)), (0 if removed == "-" else int(removed))
            prev = out.get(path, (0, 0))
            out[path] = (prev[0] + a, prev[1] + r)
    return out


def modified_items(root: Path, modified):
    work = numstat_map(root)
    staged = numstat_map(root, "--cached")
    items = []
    for code, path in modified:
        a, r = work.get(path, (0, 0))
        sa, sr = staged.get(path, (0, 0))
        _, age = stat_of(root, path)
        items.append({"path": safe_path(path), "status": code.strip(), "added": a + sa, "removed": r + sr,
                      "staged": bool(code[0].strip()), "age_days": age,
                      "evidence_command": safe_path(f"git diff -- {path}")})
    items.sort(key=lambda x: -(x["added"] + x["removed"]))
    return items


def untracked_items(root: Path, untracked):
    """Cache is grouped by its root directory; a list of 12,000 files helps nobody."""
    caches, plain = {}, []
    for path in untracked:
        if is_cache(path):
            caches.setdefault(cache_root(path), 0)
            caches[cache_root(path)] += 1
            continue
        size, age = stat_of(root, path)
        plain.append({"path": safe_path(path), "size_bytes": size, "size": human(size), "age_days": age})
    plain.sort(key=lambda x: -x["size_bytes"])
    cache_items = []
    for rel_dir in sorted(caches):
        if rel_dir.endswith("/"):
            files, size = dir_totals(root, rel_dir.rstrip("/"))
        else:
            size, _ = stat_of(root, rel_dir)
            files = 1
        cache_items.append({"path": safe_path(rel_dir), "files": files, "size_bytes": size, "size": human(size),
                            "suggested_gitignore": safe_path(rel_dir),
                            "note": "build output or installed dependency; proposed only, nothing written"})
    cache_items.sort(key=lambda x: -x["size_bytes"])
    return cache_items, plain


def submodule_items(root: Path, candidates):
    """The commits and tags between the recorded pointer and the current one are the evidence
    that says whether an advanced submodule is work or leftovers."""
    items = []
    for _, path in candidates:
        recorded = ""
        for line in git(root, "ls-files", "-s", path).splitlines():
            parts = line.split()
            if len(parts) >= 2:
                recorded = parts[1]
        current = git(root, "-C", path, "rev-parse", "HEAD").strip() if (root / path / ".git").exists() else ""
        sub = root / path
        if not recorded or not current or recorded == current:
            continue
        commits, tags = [], []
        for line in git(sub, "log", "--format=%h%x09%s", f"{recorded}..{current}").splitlines()[:MAX_ITEMS]:
            h, _, subject = line.partition("\t")
            commits.append({"commit": h, "subject": safe_text(subject)})
            for t in git(sub, "tag", "--points-at", h).split():
                tags.append(t)
        items.append({"path": safe_path(path), "recorded": recorded[:12], "current": current[:12],
                      "commits": commits, "tags": sorted(set(tags)),
                      "evidence_command": safe_path(
                          f"git -C {path} log --oneline {recorded[:12]}..{current[:12]}")})
    return items


def stash_items(root: Path):
    items = []
    # %cI, not --date=iso: --date rewrites %gd into stash@{2026-09-18 ...}, and the ref has to
    # stay stash@{0} for the evidence command to be usable.
    for line in git(root, "stash", "list", "--format=%gd%x09%cI%x09%s").splitlines():
        ref, _, rest = line.partition("\t")
        when, _, subject = rest.partition("\t")
        files = added = removed = 0
        for stat_line in git(root, "stash", "show", "--numstat", ref).splitlines():
            parts = stat_line.split("\t")
            if len(parts) == 3:
                files += 1
                added += 0 if parts[0] == "-" else int(parts[0])
                removed += 0 if parts[1] == "-" else int(parts[1])
        age = None
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", when)
        if m:
            import datetime
            age = (datetime.date.today() - datetime.date(*(int(x) for x in m.groups()))).days
        items.append({"ref": ref, "date": when[:10], "age_days": age, "files": files,
                      "added": added, "removed": removed, "subject": safe_text(subject),
                      "evidence_command": f"git stash show -p {ref}"})
    return items


def cap(items, kind):
    """Cap every category: a report is evidence, not a dump."""
    return {kind: items[:MAX_ITEMS], f"{kind}_total": len(items),
            f"{kind}_omitted": max(0, len(items) - MAX_ITEMS)}


def survey(root: Path) -> dict:
    started = time.time()
    modified_raw, untracked_raw, sub_raw = parse_status(root)
    result = {"clean": not (modified_raw or untracked_raw or sub_raw) and not git(root, "stash", "list").strip(),
              "read_only": True}
    result.update(cap(modified_items(root, modified_raw), "modified"))
    caches, plain = untracked_items(root, untracked_raw)
    result.update(cap(caches, "cache"))
    result.update(cap(plain, "untracked"))
    result.update(cap(submodule_items(root, sub_raw), "submodules"))
    result.update(cap(stash_items(root), "stashes"))
    result["elapsed_seconds"] = round(time.time() - started, 2)
    if result["elapsed_seconds"] > SLOW_SECONDS:
        # A big tree with node_modules unignored can make the per-item walk the slow part of
        # every --git-only call, including apply's step 0. Keep the counts, drop the detail.
        for kind in ("modified", "cache", "untracked", "stashes"):
            result[f"{kind}_omitted"] = result[f"{kind}_total"]
            result[kind] = []
        result["degraded"] = (f"survey took {result['elapsed_seconds']}s; reporting counts only. "
                              "Run python3 .harness/scripts/dirty.py for the itemised view.")
    result["options"] = [
        "commit the work on a branch",
        "keep it with git stash push",
        "discard it (irreversible; only if you have looked at the evidence above)",
    ]
    result["never_run_by_this_skill"] = ["git stash", "git checkout", "git clean", "git reset",
                                         "git add", "git commit"]
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=".")
    ap.add_argument("--out")
    a = ap.parse_args()
    root = find_project_root(Path(a.project))
    print(dump_json(survey(root), Path(a.out) if a.out else None))


if __name__ == "__main__":
    main()
