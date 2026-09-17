#!/usr/bin/env python3
"""Snapshots for the before/after report.

  python3 measure.py snapshot --label baseline [--include-user]   -> .harness/reports/<label>.json
  python3 measure.py compare  --before baseline --after after      -> markdown table on stdout

A snapshot = static inventory (per agent, per layer) + lint summary + runtime transcripts
+ optional manual numbers (e.g. Cursor/Antigravity context indicator, /context output).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inventory  # noqa: E402
import lint  # noqa: E402
import transcripts  # noqa: E402
from hlib import dump_json, find_project_root, read_text  # noqa: E402


def snapshot(root: Path, label: str, include_user: bool, since: str | None, manual: dict):
    inv = inventory.build(root, include_user)
    findings, _ = lint.run(root)
    counts = {}
    for x in findings:
        counts[x["severity"]] = counts.get(x["severity"], 0) + 1
        counts[x["code"]] = counts.get(x["code"], 0) + 1
    runtime = {"claude-code": transcripts.summarize(transcripts.claude_sessions(root, since), 10),
               "codex": transcripts.summarize(transcripts.codex_sessions(root, since), 10)}
    for v in runtime.values():
        v.pop("detail", None)
    snap = {"label": label, "taken_at": dt.datetime.now().isoformat(timespec="seconds"), "project": str(root),
            "agents": {a: {"always_on_est_tokens": d["always_on_est_tokens"],
                           "conditional_est_tokens": d["conditional_est_tokens"],
                           "always_on_files": len(d["always_on"]),
                           "top_always_on": sorted(d["always_on"], key=lambda x: -x["est_tokens"])[:5]}
                       for a, d in inv["agents"].items()},
            "on_demand": {k: v for k, v in inv["on_demand"].items() if k != "largest_docs"},
            "lint": counts, "runtime": runtime, "manual": manual}
    out = root / ".harness/reports" / f"{label}.json"
    dump_json(snap, out)
    return out


def pct(before, after):
    if not before:
        return "n/a"
    return f"{(after - before) / before * 100:+.0f}%"


def compare(root: Path, before: str, after: str) -> str:
    paths = [root / ".harness/reports" / f"{x}.json" for x in (before, after)]
    for p in paths:
        if not p.exists():
            sys.exit(f"snapshot not found: {p}. Run: measure.py snapshot --label {p.stem}")
    b, a = (json.loads(read_text(p)) for p in paths)
    rows = ["| Agent | Metric | Before | After | Change |", "|---|---|---|---|---|"]
    for agent in sorted(set(b["agents"]) | set(a["agents"])):
        for m in ("always_on_est_tokens", "conditional_est_tokens", "always_on_files"):
            x, y = b["agents"].get(agent, {}).get(m, 0), a["agents"].get(agent, {}).get(m, 0)
            rows.append(f"| {agent} | {m} | {x} | {y} | {pct(x, y)} |")
    for agent in ("claude-code", "codex"):
        rb, ra = b["runtime"].get(agent, {}), a["runtime"].get(agent, {})
        for m in ("median_startup_context", "median_peak_context", "sessions_with_compaction"):
            if m in rb or m in ra:
                rows.append(f"| {agent} (runtime) | {m} | {rb.get(m, '-')} | {ra.get(m, '-')} | "
                            f"{pct(rb.get(m, 0), ra.get(m, 0)) if m in rb and m in ra else 'n/a'} |")
    for sev in ("error", "warn", "info"):
        rows.append(f"| all | lint {sev} | {b['lint'].get(sev, 0)} | {a['lint'].get(sev, 0)} | "
                    f"{pct(b['lint'].get(sev, 0), a['lint'].get(sev, 0))} |")
    for k in sorted(set(b.get("manual", {})) | set(a.get("manual", {}))):
        rows.append(f"| manual | {k} | {b.get('manual', {}).get(k, '-')} | {a.get('manual', {}).get(k, '-')} | |")
    return "\n".join(rows)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot")
    s.add_argument("--project", default=".")
    s.add_argument("--label", required=True)
    s.add_argument("--include-user", action="store_true")
    s.add_argument("--since")
    s.add_argument("--manual", default="{}", help='JSON, e.g. {"cursor_context_pct": 31}')
    c = sub.add_parser("compare")
    c.add_argument("--project", default=".")
    c.add_argument("--before", required=True)
    c.add_argument("--after", required=True)
    a = ap.parse_args()
    root = find_project_root(Path(a.project))
    if a.cmd == "snapshot":
        print(f"wrote {snapshot(root, a.label, a.include_user, a.since, json.loads(a.manual))}")
    else:
        print(compare(root, a.before, a.after))


if __name__ == "__main__":
    main()
