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
from hlib import (DEFAULT_CHARS_PER_TOKEN, chars_per_token, dump_json, find_project_root,  # noqa: E402
                  load_config, ratio_note, read_text)


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
    cfg = load_config(root)
    snap = {"label": label, "taken_at": dt.datetime.now().isoformat(timespec="seconds"), "project": str(root),
            "chars_per_token": chars_per_token(cfg), "chars_per_token_note": ratio_note(cfg),
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


def calibrate(root: Path, label: str, manual: dict, apply: bool, include_user: bool = True) -> int:
    """Derive this project's real chars/token from one measured /context, and record it.

    4.00 chars per token is the figure for running English prose. A harness is not prose:
    the third pilot measured 2.10 on 600,892 characters of dense technical markdown — an
    error of 1.90x, always downwards, so a project 2x over budget reads as 1x and one at
    the threshold passes thinking it is inside. The cause is the shape of the text, not its
    language: tables, bold markers, backticked identifiers, paths, UUIDs and hashes.

    Why calibrate rather than guess by shape: a ratio derived this way was checked against a
    file set 69.7% smaller than the one that produced it and predicted it to within 0.1%. A
    heuristic over backtick density would move every number in the project, including the
    ratchet lock, with no way for anyone to tell whether it is right.
    """
    tokens = manual.get("context_memory_files_tokens") or manual.get("memory_files_tokens")
    if not tokens:
        print("Need the Memory files number from /context in a fresh session:\n"
              "  measure.py calibrate --manual '{\"context_memory_files_tokens\": 285800}'\n"
              "It must describe the same files that are on disk right now — a /context taken "
              "before the last change calibrates against a harness that no longer exists.")
        return 2
    inv = inventory.build(root, include_user=include_user)
    chars, counted = 0, []
    for agent, data in inv["agents"].items():
        if agent != "claude-code":
            continue
        for x in data["always_on"]:
            fp = Path(x["path"])
            fp = fp if fp.is_absolute() else root / fp
            text = read_text(fp)
            if text:
                chars += len(text)
                counted.append(x["path"])
    if not chars:
        print("No always-on files readable for claude-code: nothing to calibrate against.")
        return 2
    ratio = chars / float(tokens)
    cfg = load_config(root)
    current = chars_per_token(cfg)
    print(f"Always-on files read: {len(counted)} ({chars} characters)")
    print(f"/context Memory files: {tokens} tokens")
    print(f"Measured ratio: {ratio:.2f} chars/token (currently using {current:.2f}, "
          f"default {DEFAULT_CHARS_PER_TOKEN:.2f})")
    if not apply:
        print("Nothing written. Re-run with --apply to record it in .harness/config.json.")
        return 0
    cfg_path = root / ".harness/config.json"
    if not cfg_path.exists():
        print("No .harness/config.json: run install.py first, or set budgets.chars_per_token by hand.")
        return 2
    data = json.loads(read_text(cfg_path) or "{}")
    data.setdefault("budgets", {})["chars_per_token"] = round(ratio, 2)
    cfg_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote budgets.chars_per_token = {round(ratio, 2)}")
    if ratio < current:
        print(f"Every estimate in this project now grows by about {current / ratio:.2f}x, which is the "
              "point: the old numbers were a floor. H002 and the ratchet will fire on projects that "
              "looked inside their budget. Re-baseline the ratchet before committing: "
              "lint.py --update-lock")
    return 0


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
        if k == "tasks":
            continue
        rows.append(f"| manual | {k} | {b.get('manual', {}).get(k, '-')} | {a.get('manual', {}).get(k, '-')} | |")
    rows.append("")
    rows.append(f"Estimates use {b.get('chars_per_token_note') or 'an unrecorded chars/token ratio'} "
                f"(before) and {a.get('chars_per_token_note') or 'an unrecorded ratio'} (after). "
                "Static estimates are a floor, never a measurement.")
    task_rows, problems = task_cost(root, b, a)
    return "\n".join(rows + task_rows), problems


def median(xs):
    xs = sorted(xs)
    if not xs:
        return None
    mid = len(xs) // 2
    return xs[mid] if len(xs) % 2 else (xs[mid - 1] + xs[mid]) / 2


def task_cost(root, b: dict, a: dict):
    """Compare per-task cost against the always-on reduction, and refuse the pair that cannot hold.

    A restructure trades guaranteed context for conditional context. After it, a task can
    pass two ways: the scoped rule fired and the agent already knew (cheaper), or it did not
    fire and the agent hunted the answer down (dearer). Both end in PASS, and the verdict
    cannot tell them apart. The cost can.

    In the third pilot two tasks came back at -2.4% and +1.6% against an always-on 96.5%
    smaller. That does not add up, and it was the signal that the environment was wrong
    (F11) — printed under the tables, read as success, twice. A signal that depends on
    someone remembering to look at it is not ready, so this one stops the battery instead.

    Task numbers come from the person who ran the tasks in a fresh session; this only checks
    them. Pass them in the after snapshot:
      --manual '{"tasks": [{"id": "T1", "tokens_before": 41000, "tokens_after": 12000}]}'
    """
    cfg = load_config(root)
    big = float((cfg.get("benchmark") or {}).get("big_reduction_pct", 50))
    floor = float((cfg.get("benchmark") or {}).get("min_cost_delta_pct", 10))
    tasks = (a.get("manual") or {}).get("tasks") or []
    if not tasks:
        # Said out loud, but not a refusal: not measuring the behavioural half is a normal
        # state (the tasks are optional, and the user runs them). Reporting it as a result
        # without saying so is what is not allowed.
        return (["", "No per-task cost recorded, so the behavioural half of this comparison was not "
                     "measured. The numbers above are static file sizes: they say the harness got "
                     "smaller, not that the agent still works. Record tokens and tool uses per task "
                     "(see references/rubric.md) or say plainly in the report that it was not measured."],
                [])
    rows = ["", "| Task | Tokens before | Tokens after | Change | Tool uses before | after |", "|---|---|---|---|---|---|"]
    deltas = []
    for t in tasks:
        tb, ta = t.get("tokens_before"), t.get("tokens_after")
        change = pct(tb, ta) if tb and ta is not None else "n/a"
        if tb and ta is not None:
            deltas.append(abs((ta - tb) / tb * 100))
        rows.append(f"| {t.get('id', '?')} | {tb or '-'} | {ta if ta is not None else '-'} | {change} | "
                    f"{t.get('tool_uses_before', '-')} | {t.get('tool_uses_after', '-')} |")
    problems = []
    reductions = []
    for agent in sorted(set(b["agents"]) & set(a["agents"])):
        x = b["agents"][agent].get("always_on_est_tokens", 0)
        y = a["agents"][agent].get("always_on_est_tokens", 0)
        if x:
            reductions.append((x - y) / x * 100)
    claimed = max(reductions or [0])
    med = median(deltas)
    if med is not None:
        rows.append("")
        rows.append(f"Declared always-on reduction: {claimed:.1f}%. Median per-task cost change: {med:.1f}%.")
    if claimed > big and med is not None and med < floor:
        problems.append(
            f"always-on fell {claimed:.1f}% but the median per-task cost moved only {med:.1f}%. Those two "
            "numbers cannot both be right. Either the environment that produced the 'after' is not the one "
            "the audit changed (run benchenv.py against every directory the tasks ran in), or the tasks "
            "did not exercise the moved content at all. Do not report these verdicts as a result.")
    return rows, problems


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
    k = sub.add_parser("calibrate")
    k.add_argument("--project", default=".")
    k.add_argument("--label", default="baseline", help="snapshot whose always-on files the /context number covers")
    k.add_argument("--manual", default="{}", help='JSON with context_memory_files_tokens')
    k.add_argument("--apply", action="store_true", help="write the measured ratio to .harness/config.json")
    k.add_argument("--project-only", action="store_true",
                   help="ignore user-level memory files (only if the /context number excluded them too)")
    a = ap.parse_args()
    root = find_project_root(Path(a.project))
    if a.cmd == "snapshot":
        print(f"wrote {snapshot(root, a.label, a.include_user, a.since, json.loads(a.manual))}")
    elif a.cmd == "calibrate":
        sys.exit(calibrate(root, a.label, json.loads(a.manual), a.apply, not a.project_only))
    else:
        text, problems = compare(root, a.before, a.after)
        print(text)
        for x in problems:
            print(f"\nSTOP: {x}")
        sys.exit(2 if problems else 0)


if __name__ == "__main__":
    main()
