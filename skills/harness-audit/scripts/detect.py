#!/usr/bin/env python3
"""Pre-interview detection. The skill shows these findings to the user and asks to confirm.

Detects: agents configured in the project, Obsidian vaults (inside the repo, in parent
folders, and in common locations), candidate docs folders, git state.

Usage: python3 detect.py [--project PATH] [--search ~/Some/Folder ...] [--git-only]

--git-only prints just the git state (clean tree, distance from the upstream). apply
reruns it, because apply can happen in a different session hours after diagnose.
"""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

import dirty
from hlib import HOME, detect_agents, dump_json, find_project_root, git, git_environment, rel, upstream_state

COMMON_VAULT_PARENTS = [
    HOME / "Documents", HOME / "Obsidian", HOME / "obsidian", HOME / "Vaults", HOME / "Notes",
    HOME / "Library/Mobile Documents/iCloud~md~obsidian/Documents",
    HOME / "Dropbox", HOME / "OneDrive", HOME / "Google Drive", HOME,
]


def vaults_under(base: Path, max_depth: int):
    found = []
    if not base.is_dir():
        return found
    base_depth = len(base.parts)
    for dirpath, dirnames, _ in os.walk(base):
        depth = len(Path(dirpath).parts) - base_depth
        if ".obsidian" in dirnames:
            found.append(Path(dirpath))
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in ("node_modules", "Library")
                       and depth < max_depth]
    return found


def name_tokens(name: str) -> set:
    """The parts of a project name worth matching a folder against.

    Repository directories carry suffixes the note folder does not: `tavoloo` in the vault
    against `tavoloo-fmsolutions-main` on disk. Exact-name matching missed that in the third
    pilot. Tokens shorter than 4 characters are dropped — `api`, `web` or `app` would match
    half a vault.
    """
    parts = {p for p in re.split(r"[-_. ]+", name.lower()) if len(p) >= 4}
    if len(name) >= 4:
        parts.add(name.lower())
    return parts


def folders_like_project(vault: Path, project_name: str):
    tokens = name_tokens(project_name)
    if not tokens:
        return []
    out = []
    for d in vault.rglob("*"):
        if not d.is_dir() or ".obsidian" in d.parts:
            continue
        dn = d.name.lower()
        if dn in tokens or any(t in dn for t in tokens):
            out.append(d)
    return sorted(out)


def topology(root: Path, vault: Path) -> str:
    r, v = root.resolve(), vault.resolve()
    if v == r or str(v).startswith(str(r) + os.sep):
        return "inside-repo"
    if str(r).startswith(str(v) + os.sep):
        return "repo-inside-vault"
    return "external"


def git_state(root: Path) -> dict:
    return {
        "project": str(root),
        "is_git_repo": bool(git(root, "rev-parse", "--is-inside-work-tree").strip()),
        "branch": git(root, "rev-parse", "--abbrev-ref", "HEAD").strip(),
        "uncommitted_changes": len([l for l in git(root, "status", "--porcelain").splitlines() if l]),
        "dirty": dirty.survey(root),
        "upstream": upstream_state(root),
        "git_environment": git_environment(),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=".")
    ap.add_argument("--git-only", action="store_true", help="print only the git state (fast)")
    ap.add_argument("--search", nargs="*", default=[], help="extra folders to scan for vaults")
    a = ap.parse_args()
    root = find_project_root(Path(a.project))
    if a.git_only:
        print(dump_json(git_state(root), None))
        return

    candidates = set(vaults_under(root, 4))
    for p in root.parents:
        if (p / ".obsidian").is_dir():
            candidates.add(p)
    for extra in a.search:
        candidates.update(vaults_under(Path(extra).expanduser(), 3))
    for base in COMMON_VAULT_PARENTS:
        candidates.update(vaults_under(base, 2 if base != HOME else 1))

    vaults = []
    for v in sorted(candidates):
        project_folders = [rel(v, d) for d in folders_like_project(v, root.name)][:5]
        vaults.append({"path": str(v), "topology": topology(root, v),
                       "folders_named_like_project": project_folders,
                       # An empty match list is not an answer, it is the absence of one. The
                       # third pilot read `[]` and nearly concluded the project had no
                       # knowledge layer at all, while `B01 Projetos/tavoloo/` sat there with
                       # an overview, 204 lines of decisions and 361 of log. Listing the
                       # top level costs nothing and lets a human settle it in one look.
                       "top_level_folders": sorted(d.name for d in v.iterdir()
                                                   if d.is_dir() and not d.name.startswith("."))[:40]})

    docs_candidates = [d for d in ("docs", "doc", "documentation", "wiki", "notes", "knowledge", "agent_docs")
                       if (root / d).is_dir()]
    result = {
        **git_state(root),
        "agents_detected": detect_agents(root),
        "obsidian_vaults_found": vaults,
        "docs_folder_candidates": docs_candidates,
        "harness_installed": (root / ".harness/config.json").exists(),
        "questions_to_confirm": [
            "Which agents do you use on this project? (detected list is a suggestion)",
            "Do you use Obsidian with this project? If yes, which vault and which folder holds this project's notes?",
            "Should agent-facing knowledge live in the repo (docs/) or in the vault folder?",
            "Language for reports?",
        ],
    }
    print(dump_json(result, None))


if __name__ == "__main__":
    main()
