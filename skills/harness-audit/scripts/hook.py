#!/usr/bin/env python3
"""One hook script for every agent. Installed at .harness/scripts/hook.py.

  python3 .harness/scripts/hook.py --agent claude-code --event post-edit
  python3 .harness/scripts/hook.py --agent cursor      --event stop
Events: post-edit | stop | session-start

Protocols (checked Sept 2026, see references/agents/*):
  claude-code  exit 2 + stderr is fed back to Claude; Stop honors stop_hook_active.
  codex        Claude-style hooks: exit 2 + stderr (verify against your Codex version).
  cursor       afterFileEdit cannot talk to the agent: we record the edit and report on stop
               via {"followup_message": ...}; sessionStart returns {"additional_context": ...}.
  antigravity  best effort: stderr + exit 2. Pre-commit and CI remain the guaranteed gate.
Hooks never crash the agent session: any internal error exits 0.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

PATCH_RE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", re.M)
PATH_KEYS = {"file_path", "filePath", "path", "notebook_path", "target_file", "TargetFile", "AbsolutePath"}
MAX_BLOCKS = 2


def collect_paths(obj, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in PATH_KEYS and isinstance(v, str):
                out.add(v)
            else:
                collect_paths(v, out)
    elif isinstance(obj, list):
        for v in obj:
            collect_paths(v, out)
    elif isinstance(obj, str) and "*** " in obj:
        out.update(m.strip() for m in PATCH_RE.findall(obj))


def state_file(root: Path) -> Path:
    return root / ".harness/state/session.json"


def load_state(root: Path) -> dict:
    try:
        return json.loads(state_file(root).read_text())
    except (OSError, ValueError):
        return {"edits": [], "blocks": {}}


def save_state(root: Path, st: dict):
    p = state_file(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(st))


def session_id(payload: dict) -> str:
    return str(payload.get("session_id") or payload.get("conversation_id") or payload.get("sessionId") or "default")


def feedback(agent: str, event: str, msg: str, payload: dict, root: Path):
    """Emit a message the agent will act on, respecting loop guards."""
    st = load_state(root)
    sid = session_id(payload)
    if event == "stop":
        if payload.get("stop_hook_active") or int(payload.get("loop_count") or 0) >= MAX_BLOCKS:
            return 0
        blocks = st["blocks"].get(sid, 0)
        if blocks >= MAX_BLOCKS:
            return 0
        st["blocks"][sid] = blocks + 1
        save_state(root, st)
    if agent == "cursor":
        if event == "stop":
            print(json.dumps({"followup_message": msg}))
        return 0
    print(msg, file=sys.stderr)
    return 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", required=True, choices=["claude-code", "codex", "cursor", "antigravity"])
    ap.add_argument("--event", required=True, choices=["post-edit", "stop", "session-start"])
    ap.add_argument("--project", default=None)
    a = ap.parse_args()
    raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except ValueError:
        payload = {}

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import lint  # noqa: E402
    from hlib import changed_files, doc_rel, find_project_root, load_config, log_path, rel  # noqa: E402

    start = a.project or payload.get("cwd") or (payload.get("workspace_roots") or [None])[0] or "."
    root = find_project_root(Path(start))
    cfg = load_config(root)

    if a.event == "post-edit":
        paths = set()
        collect_paths(payload, paths)
        rels = [rel(root, Path(p) if Path(p).is_absolute() else root / p) for p in paths]
        relevant = [r for r in rels if lint.is_harness_file(root, cfg, r)]
        if not relevant:
            return 0
        st = load_state(root)
        st["edits"] = sorted(set(st["edits"]) | set(relevant))
        st.setdefault("first_edit", time.time())
        st["updated"] = time.time()
        save_state(root, st)
        if a.agent == "cursor":
            return 0
        findings, _ = lint.run(root, relevant)
        errors = [x for x in findings if x["severity"] == "error" and x["code"] != "H008"]
        if errors:
            return feedback(a.agent, a.event, "Harness check failed for the file you just edited. Fix before continuing:\n"
                            + lint.format_text(errors), payload, root)
        return 0

    if a.event == "stop":
        st = load_state(root)
        touched = set(st.get("edits", []))
        touched |= {f for f in changed_files(root) if lint.is_harness_file(root, cfg, f)}
        if not touched:
            return 0
        findings, _ = lint.run(root, sorted(touched))
        problems = [x for x in findings if x["severity"] == "error"]
        docs_touched = [t for t in touched if lint.is_doc(root, cfg, t)]
        lp = rel(root, log_path(root, cfg))
        log_file = log_path(root, cfg)
        since = st.get("first_edit") or st.get("updated")
        log_fresh = lp in touched or bool(log_file.exists() and since and log_file.stat().st_mtime >= since)
        if docs_touched and not log_fresh and log_file.exists():
            problems.append({"code": "H018", "severity": "error", "path": lp,
                             "message": f"{len(docs_touched)} doc(s) changed but the log was not updated",
                             "fix": f"Append one line to {lp}: ## [YYYY-MM-DD] <kind> | <what changed>"})
        if problems:
            return feedback(a.agent, a.event, "Before finishing, put the harness back in order:\n"
                            + lint.format_text(problems)
                            + "\nThen run: python3 .harness/scripts/build_index.py && python3 .harness/scripts/lint.py",
                            payload, root)
        st["edits"], st["blocks"] = [], {}
        st.pop("first_edit", None)
        save_state(root, st)
        return 0

    if a.event == "session-start":
        f = lint.Findings()
        lint.check_budgets(root, cfg, f)
        over = [x for x in f if x["code"] in ("H002", "H006", "H015")]
        if not over:
            return 0
        msg = ("Harness alert: " + "; ".join(f"{x['path']}: {x['message']}" for x in over)
               + ". Follow .harness/PLACEMENT.md and do not add to always-on files.")
        if a.agent == "cursor":
            print(json.dumps({"additional_context": msg}))
        else:
            print(msg)
        return 0
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # never break the agent session
        print(f"harness hook internal error (ignored): {exc}", file=sys.stderr)
        sys.exit(0)
