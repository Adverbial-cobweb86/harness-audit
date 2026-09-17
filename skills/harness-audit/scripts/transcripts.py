#!/usr/bin/env python3
"""Runtime context metrics from local transcripts.

Claude Code: ~/.claude/projects/<encoded-path>/*.jsonl (usage per assistant message).
Codex:       ~/.codex/sessions/**/rollout-*.jsonl (token_count events, filtered by cwd).
Cursor and Antigravity keep no stable local transcript format: measure via their UI
(context indicator / agy inspect) and record numbers manually in the report.

Context per request = input_tokens + cache_read_input_tokens + cache_creation_input_tokens.
Output tokens are ignored: Claude Code JSONL is known to under-count them.

Usage: python3 transcripts.py --project PATH [--agent claude-code|codex] [--last 10] [--since ISO]
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

from hlib import HOME, dump_json, find_project_root


def _lines(path: Path):
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def claude_sessions(root: Path, since: str | None):
    enc = "-" + str(root.resolve()).strip("/").replace("/", "-").replace(".", "-")
    base = HOME / ".claude/projects" / enc
    sessions = []
    for f in sorted(base.glob("*.jsonl"), key=lambda p: p.stat().st_mtime):
        seen, contexts, compactions, first_ts = set(), [], 0, None
        for ev in _lines(f):
            first_ts = first_ts or ev.get("timestamp")
            if ev.get("isCompactSummary") or ev.get("subtype") == "compact_boundary":
                compactions += 1
            msg = ev.get("message") or {}
            usage = msg.get("usage")
            if ev.get("type") != "assistant" or not usage:
                continue
            mid = msg.get("id")
            if mid in seen:
                continue
            seen.add(mid)
            contexts.append(int(usage.get("input_tokens", 0)) + int(usage.get("cache_read_input_tokens", 0))
                            + int(usage.get("cache_creation_input_tokens", 0)))
        if not contexts or (since and first_ts and first_ts < since):
            continue
        sessions.append({"file": f.name, "started": first_ts, "requests": len(contexts),
                         "startup_context": contexts[0], "peak_context": max(contexts),
                         "mean_context": round(statistics.mean(contexts)), "compactions": compactions})
    return sessions


def codex_sessions(root: Path, since: str | None):
    base = HOME / ".codex/sessions"
    target = str(root.resolve())
    sessions = []
    for f in sorted(base.rglob("rollout-*.jsonl"), key=lambda p: p.stat().st_mtime):
        cwd, contexts, first_ts, compactions = None, [], None, 0
        for ev in _lines(f):
            first_ts = first_ts or ev.get("timestamp")
            payload = ev.get("payload") or {}
            if ev.get("type") == "session_meta":
                cwd = payload.get("cwd")
            if ev.get("type") == "compacted" or payload.get("type") == "context_compacted":
                compactions += 1
            if payload.get("type") == "token_count":
                last = ((payload.get("info") or {}).get("last_token_usage") or {})
                if last:
                    contexts.append(int(last.get("input_tokens", 0)))
        if cwd != target or not contexts or (since and first_ts and first_ts < since):
            continue
        sessions.append({"file": f.name, "started": first_ts, "requests": len(contexts),
                         "startup_context": contexts[0], "peak_context": max(contexts),
                         "mean_context": round(statistics.mean(contexts)), "compactions": compactions})
    return sessions


def summarize(sessions, last):
    s = sessions[-last:] if last else sessions
    if not s:
        return {"sessions": 0}
    med = lambda k: round(statistics.median(x[k] for x in s))
    return {"sessions": len(s), "median_startup_context": med("startup_context"),
            "median_peak_context": med("peak_context"), "median_requests": med("requests"),
            "sessions_with_compaction": sum(1 for x in s if x["compactions"]), "detail": s}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=".")
    ap.add_argument("--agent", choices=["claude-code", "codex", "all"], default="all")
    ap.add_argument("--last", type=int, default=10)
    ap.add_argument("--since")
    ap.add_argument("--out")
    a = ap.parse_args()
    root = find_project_root(Path(a.project))
    result = {}
    if a.agent in ("claude-code", "all"):
        result["claude-code"] = summarize(claude_sessions(root, a.since), a.last)
    if a.agent in ("codex", "all"):
        result["codex"] = summarize(codex_sessions(root, a.since), a.last)
    result["manual"] = {"cursor": "read context usage in the chat UI", "antigravity": "use agy inspect / session stats"}
    print(dump_json(result, Path(a.out) if a.out else None))


if __name__ == "__main__":
    main()
