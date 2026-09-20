#!/usr/bin/env python3
"""Harness lint. The sensor that keeps the house organized after the audit.

Usage:
  python3 lint.py [--project PATH]                 full check
  python3 lint.py --files a.md b.md                only checks relevant to these files
  python3 lint.py --staged                         files staged in git (pre-commit)
  python3 lint.py --json                           machine-readable output
  python3 lint.py --strict                         warnings also fail
Exit code: 0 clean, 1 errors (or warnings with --strict).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

import build_index
import inventory
import sync
from hlib import (as_list, changed_files, chars_per_token, doc_rel, docs_root, estimate_tokens,
                  find_project_root, index_path, iter_md, load_config, match_any, parse_frontmatter,
                  ratio_note, read_text, rel)

CHECKS = {
    "H001": "Entry file over line budget",
    "H002": "Always-on context over token budget",
    "H003": "@import of docs in CLAUDE.md (loads every session)",
    "H004": "Claude rule without paths (always loaded)",
    "H005": "Cursor rule problem (.md ignored, alwaysApply too large, legacy .cursorrules)",
    "H006": "Codex AGENTS.md chain over project_doc_max_bytes (silent truncation)",
    "H007": "Doc missing required frontmatter or invalid status",
    "H008": "Index out of date",
    "H009": "Broken relative link",
    "H010": "Doc outside the placement map",
    "H011": "Duplicated instruction content across entry files",
    "H012": "Generated projection out of sync or hand-edited",
    "H013": "Volatile content in an always-on file",
    "H014": "Stale or misplaced plan/doc",
    "H015": "Always-on budget grew past the ratchet lock",
    "H016": "Skill description too long for listing budget",
    "H017": "Wikilink without resolvable path in agent-facing doc",
    "H019": "Budgets are still the transitional ones measured at install",
    "H020": "CLAUDE.local.md switches the team's AGENTS.md off for one person",
    "H021": "CLAUDE.md over 4 MiB: Claude Code skips the whole file",
    "H022": "AGENTS.override.md: Codex reads it, Claude Code never does",
    "H023": "Entry files forked: shared paragraphs, but one side is materially behind",
    "H024": "Ratchet is on but has no baseline to compare against",
}

CLAUDE_MD_LIMIT = 4 * 1024 * 1024

VOLATILE = re.compile(r"(\b20\d\d-\d\d-\d\d\b|\bcurrently\b|\bthis sprint\b|\bstatus:\s|\bin progress\b|\bTODO\b|\batualmente\b|\bem andamento\b)", re.I)
LINK = re.compile(r"\[[^\]]*\]\(([^)#\s]+)(?:#[^)]*)?\)")
WIKILINK = re.compile(r"\[\[([^\]|#]+)")


class Findings(list):
    """The findings, minus whatever the project declared it will not fix.

    A lint that cannot coexist with documentation quoting real syntax gets switched off
    whole. The third pilot hit it with H017 over `[[PRODUCT:<uuid>|name]]`, which is this
    project's own product-link marker: following the suggested fix would have corrupted the
    documentation of a live protocol.
    """

    def __init__(self, cfg=None):
        super().__init__()
        self.suppress = ((cfg or {}).get("lint") or {}).get("suppress") or {}

    def add(self, code, sev, path, msg, fix=""):
        for pattern in as_list(self.suppress.get(code)):
            # The path glob is anchored; the message one is not, because what identifies a
            # false positive is usually a fragment of it (`PRODUCT:*`), not the whole line.
            if match_any(str(path), [pattern]) or match_any(msg, [f"*{pattern}*"]):
                return
        self.append({"code": code, "severity": sev, "path": path, "message": msg, "fix": fix})


ENTRY = ("CLAUDE.md", "CLAUDE.local.md", "AGENTS.md", "GEMINI.md", ".cursorrules")
# Claude Code never reads AGENTS.override.md, so it stays out of ENTRY: the entry-file
# budget that ENTRY feeds is the one the Claude Code ratchet tightens, and a file that
# agent never loads cannot move it. Codex reads it with precedence, and that is where it
# is counted (inventory.codex_layers, always-on). H022 still reports that it exists.
CODEX_ONLY_ENTRY = ("AGENTS.override.md",)


def is_doc(root, cfg, r: str) -> bool:
    p = Path(r) if Path(r).is_absolute() else root / r
    return r.endswith(".md") and bool(doc_rel(root, cfg, p))


def is_harness_file(root, cfg, r: str) -> bool:
    return (r.endswith((".md", ".mdc")) and (is_doc(root, cfg, r) or r in ENTRY or r in CODEX_ONLY_ENTRY or
            r.startswith((".claude/", ".cursor/", ".agents/", ".harness/"))))


def check_entry_files(root, cfg, f: Findings, only=None):
    budget = int(cfg["budgets"]["entry_file_lines"])
    texts = {}
    for name in ("CLAUDE.md", "AGENTS.md", "GEMINI.md", "AGENTS.override.md"):
        p = root / name
        if not p.is_file() or (only is not None and name not in only):
            continue
        text = read_text(p)
        texts[name] = text
        n = text.count("\n") + 1
        if n > budget:
            f.add("H001", "error", name, f"{n} lines (budget {budget})",
                  "Move procedures to skills, scoped rules to .harness/rules, knowledge to docs/ with an index pointer.")
        body = re.sub(r"<!--.*?-->", "", text, flags=re.S)
        vol = VOLATILE.findall(re.sub(r"```.*?```", "", body, flags=re.S))
        if vol:
            f.add("H013", "warn", name, f"volatile content found ({', '.join(sorted(set(v.lower() for v in vol))[:4])})",
                  "Keep dates, status and 'current work' in docs/plans or docs/log.md so the prefix stays cache-stable.")
        if name == "CLAUDE.md":
            for ref in inventory.IMPORT_RE.findall(inventory.strip_code(text)):
                if ref.rstrip("/") in ("AGENTS.md", "./AGENTS.md"):
                    continue
                if "/" in ref or ref.endswith(".md"):
                    f.add("H003", "warn", name, f"@{ref} is expanded into every session",
                          "Replace the import with a plain path in the routing table so it is read on demand.")
    # Shared paragraphs between entry files mean one of two different things, and the
    # expensive one is not the obvious one. If the files are the same size, the content is
    # paid twice (H011). If one is materially shorter, they are a fork: they started as a
    # copy and one side moved on. The third pilot found 41 shared paragraphs between a
    # CLAUDE.md of 6,198 lines and an AGENTS.md of 1,754 — two months and 4,444 lines
    # apart, and nobody paid twice, because no agent reads both. Codex was running on the
    # older truth, truncated, with no signal at all. Calling that "paid twice" sends the
    # reader to look for a duplication that is not the problem.
    names = [n for n in texts if n != "AGENTS.override.md"]
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            pa = {p.strip() for p in re.split(r"\n\s*\n", texts[a]) if len(p.strip()) > 120}
            pb = {p.strip() for p in re.split(r"\n\s*\n", texts[b]) if len(p.strip()) > 120}
            shared = pa & pb
            if not shared:
                continue
            la, lb = texts[a].count("\n") + 1, texts[b].count("\n") + 1
            big, small = (a, b) if la >= lb else (b, a)
            nbig, nsmall = max(la, lb), min(la, lb)
            # Dates are deliberately not read: mtime lies after a clone, and an "updated on"
            # stamp inside the file is not parseable in general. Line counts are provable.
            if nbig and (nbig - nsmall) / nbig > 0.20:
                f.add("H023", "warn", f"{a} + {b}",
                      f"{len(shared)} shared paragraph(s), but {small} has {nsmall} lines against "
                      f"{nbig} in {big}: these are a fork, not a duplication. No agent reads both "
                      f"(Claude Code reads CLAUDE.md, Codex reads AGENTS.md), so nobody pays twice — "
                      f"whoever reads {small} is running on the older truth, silently",
                      "Decide which file is canonical, make the other import or mirror it, and check "
                      "the resolution line in the inventory for who reads what here.")
            else:
                f.add("H011", "warn", f"{a} + {b}", f"{len(shared)} identical paragraph(s) paid twice",
                      "Keep content in AGENTS.md; CLAUDE.md should import it with @AGENTS.md; GEMINI.md should not repeat it.")


def check_instruction_resolution(root, cfg, f: Findings):
    """Which instruction file each agent ends up reading, and the three ways it goes wrong.

    The setting that decides it lives in user and managed settings, so the lint reads
    them: the answer is wrong without them, and a pre-commit gate that reports the wrong
    file is worse than none.
    """
    res = inventory.instruction_resolution(root, read_user=True)
    canonical_agents_md = bool(res["agents_md_files"]) and res["claude_md_files"] == res["claude_local_md"]
    if (canonical_agents_md and res["claude_local_md"] and not res["agents_md_imported_by"]
            and res["instruction_files"] != "claude-md-and-agents-md"):
        f.add("H020", "warn", res["claude_local_md"][0],
              "this project's instructions live in " + ", ".join(res["agents_md_files"]) +
              ", and a CLAUDE.local.md in the tree stops Claude Code from reading them — for you only. "
              "The file is gitignored, so the repository still looks right and nobody else sees the loss",
              "Either add @AGENTS.md at the top of the CLAUDE.local.md (an import is read once, never twice), "
              "or set Project instructions to claude-md-and-agents-md in ~/.claude/settings.json under "
              'pluginConfigs["agents-md@builtin"].options.instructionFiles (project and local settings are ignored).')
    for r in res["claude_md_files"]:
        p = (root / r) if not Path(r).is_absolute() else Path(r)
        try:
            size = p.stat().st_size
        except OSError:
            continue
        if size > CLAUDE_MD_LIMIT:
            f.add("H021", "error", r, f"{size / 1048576:.1f} MiB: Claude Code skips a CLAUDE.md over 4 MiB "
                                      "entirely — it is not truncated, none of it loads",
                  "Split it: keep a map under the budget and move the rest to docs/ read on demand.")
    if res["agents_override_md"]:
        f.add("H022", "warn", res["agents_override_md"],
              "Codex reads AGENTS.override.md with precedence over AGENTS.md; Claude Code never reads it "
              "(nor AGENTS.local.md, nor anything under .agents/). Two agents, two truths",
              "Move the content into AGENTS.md, or keep the override and state in AGENTS.md which agent "
              "reads which file.")
    return res


def check_budgets(root, cfg, f: Findings):
    inv = inventory.build(root, include_user=False)
    budget = int(cfg["budgets"]["always_on_tokens"])
    tr = cfg.get("budgets_transitional") or {}
    if tr:
        # A transitional budget that nobody ever tightens is just a loose budget with a
        # nice name. Say so on every run until someone closes it.
        f.add("H019", "warn", ".harness/config.json",
              f"budgets are a photograph of this project on {tr.get('measured_on', 'install day')} "
              f"({budget} always-on tokens, {cfg['budgets']['entry_file_lines']} entry-file lines), "
              f"not the targets ({tr.get('targets', {}).get('always_on_tokens')} / "
              f"{tr.get('targets', {}).get('entry_file_lines')})",
              "Tighten them to what the project measures now with: lint.py --update-lock")
    lock_path = root / ".harness/budgets.lock.json"
    lock = json.loads(read_text(lock_path)) if lock_path.exists() else {}
    window = cfg["budgets"].get("context_window")
    for agent, data in inv["agents"].items():
        tok = data["always_on_est_tokens"]
        if tok > budget:
            top = sorted(data["always_on"], key=lambda x: -x["est_tokens"])[:3]
            biggest = ", ".join(f"{x['path']} ~{x['est_tokens']}" for x in top)
            if window and tok > int(window):
                # A different kind of failure from "over budget", and the more actionable of
                # the two: the harness alone does not fit the window, so the session cannot
                # start at all — not for a trivial question, not with no tools loaded.
                f.add("H002", "error", agent,
                      f"~{tok} always-on tokens against a context window of {window}: this project "
                      f"does not open on that model at all, before any system prompt, tool definition "
                      f"or question. Not over budget — a hard failure. Biggest: {biggest}",
                      "Run /harness-audit diagnose. Until the always-on fits the window, the only "
                      "models that can open this project are the ones with a larger one.")
            else:
                f.add("H002", "error", agent, f"~{tok} tokens always-on (budget {budget}, floor, "
                      f"{ratio_note(cfg)}); biggest: {biggest}",
                      "Run /harness-audit diagnose to plan the reduction.")
        locked = (lock.get(agent) or {}).get("always_on_est_tokens")
        if cfg.get("ratchet") and locked and tok > locked * 1.05:
            f.add("H015", "error", agent, f"always-on grew from ~{locked} to ~{tok} tokens",
                  "Reduce it, or approve the increase explicitly with: lint.py --update-lock")
        # No lock means the ratchet reads nothing and the `and` above short-circuits: the
        # gate turns itself off, quietly, and that is the state of every branch older than
        # the audit — exactly the case a regressive merge produces. "I cannot measure" must
        # not be reported as "passed".
        if cfg.get("ratchet") and not locked:
            f.add("H024", "warn", agent,
                  "ratchet is enabled but .harness/budgets.lock.json has no baseline for this agent, "
                  f"so nothing is compared and the gate passes whatever arrives (~{tok} tokens now)",
                  "Record the baseline with: lint.py --update-lock")
        for x in data["always_on"]:
            if x.get("note", "").startswith("TRUNCATED"):
                f.add("H006", "error", x["path"], x["note"], "Split AGENTS.md: keep a map, move detail to docs/.")
    return inv


def check_rules(root, cfg, f: Findings, only=None):
    rule_budget = int(cfg["budgets"]["rule_tokens"])
    for r in iter_md(root / ".claude/rules", root=root):
        rp = rel(root, r)
        if only is not None and rp not in only:
            continue
        fm, _ = parse_frontmatter(read_text(r))
        if not as_list(fm.get("paths")):
            f.add("H004", "warn", rp, "no paths frontmatter: loaded in every session",
                  "Add paths globs in the canonical .harness/rules source, or move the content to CLAUDE.md if truly global.")
    for r in iter_md(root / ".cursor/rules", root=root):
        rp = rel(root, r)
        if only is not None and rp not in only:
            continue
        text = read_text(r)
        if r.suffix == ".md":
            f.add("H005", "error", rp, ".md files in .cursor/rules are ignored by Cursor", "Rename to .mdc with frontmatter.")
            continue
        fm, _ = parse_frontmatter(text)
        if fm.get("alwaysApply") is True and estimate_tokens(text) > rule_budget:
            f.add("H005", "warn", rp, f"alwaysApply rule ~{estimate_tokens(text)} tokens", "Scope it with globs.")
    if (root / ".cursorrules").exists():
        f.add("H005", "warn", ".cursorrules", "legacy file, deprecated by Cursor", "Migrate to AGENTS.md or .cursor/rules/*.mdc.")


def check_docs(root, cfg, f: Findings, only=None):
    droot = docs_root(root, cfg)
    required = cfg.get("required_frontmatter", [])
    allowed = set(cfg.get("allowed_status", []))
    exclude = cfg["index"].get("exclude", [])
    placement = [k.strip("/") for k in (cfg.get("placement") or {})]
    stale_days = int(cfg["budgets"].get("stale_days", 120))
    today = dt.date.today()
    for p in iter_md(droot):
        rp, dp = rel(root, p), doc_rel(root, cfg, p)
        if only is not None and rp not in only:
            continue
        if match_any(dp, exclude):
            continue
        text = read_text(p)
        fm, body = parse_frontmatter(text)
        missing = [k for k in required if not fm.get(k)]
        if missing:
            f.add("H007", "error", rp, f"missing frontmatter: {', '.join(missing)}",
                  "Add description (one line), updated (YYYY-MM-DD), status, and read_when.")
        if fm.get("status") and allowed and str(fm.get("status")) not in allowed:
            f.add("H007", "warn", rp, f"status '{fm.get('status')}' not in {sorted(allowed)}")
        if placement and not any(dp.startswith(pl + "/") for pl in placement):
            f.add("H010", "warn", rp, "not inside any placement-map folder",
                  "Move it to the folder its kind belongs to (see .harness/PLACEMENT.md).")
        if dp.startswith("plans/active/") and str(fm.get("status")) in ("completed", "archived"):
            f.add("H014", "warn", rp, "completed plan still in plans/active", "Move to plans/completed/.")
        try:
            upd = dt.date.fromisoformat(str(fm.get("updated"))[:10])
            if (today - upd).days > stale_days and str(fm.get("status")) == "active":
                f.add("H014", "info", rp, f"not updated for {(today - upd).days} days",
                      "Confirm it is still true or mark superseded.")
        except ValueError:
            pass
        for target in LINK.findall(re.sub(r"```.*?```", "", body, flags=re.S)):
            if re.match(r"^[a-z]+:", target):
                continue
            if not (p.parent / target.replace("%20", " ")).resolve().exists():
                f.add("H009", "warn", rp, f"broken link: {target}")
        for w in WIKILINK.findall(body):
            # `[[PRODUCT:<uuid>|name]]` is not a note reference, it is a protocol this
            # project documents. A colon or an angle-bracket placeholder inside the target
            # is the signature of machine syntax, and "prefer a markdown link" applied to it
            # would corrupt the documentation of a live wire format.
            if ":" in w or "<" in w:
                continue
            if not list(droot.rglob(w.strip().split("/")[-1] + ".md")):
                f.add("H017", "info", rp, f"wikilink [[{w.strip()}]] does not resolve to a file",
                      "Agents do not resolve wikilinks: prefer a markdown link with a relative path.")


def check_generated(root, cfg, f: Findings):
    for problem in sync.run(root, check=True):
        f.add("H012", "error", problem.split(": ", 1)[-1], problem,
              "Edit the canonical source in .harness/, then run python3 .harness/scripts/sync.py")


def check_index(root, cfg, f: Findings):
    if not docs_root(root, cfg).is_dir():
        return
    path = index_path(root, cfg)
    current = read_text(path) if path.exists() else ""
    new = build_index.merged(current, build_index.render(root, cfg))
    if new.strip() != current.strip():
        f.add("H008", "error", rel(root, path), "index does not match docs frontmatter",
              "Run python3 .harness/scripts/build_index.py")


def check_skills(root, cfg, f: Findings):
    limit = int(cfg["budgets"].get("skill_description_chars", 400))
    for d in (".harness/skills", ".claude/skills", ".cursor/skills", ".agents/skills"):
        for sk in (root / d).glob("*/SKILL.md"):
            fm, _ = parse_frontmatter(read_text(sk))
            n = len(str(fm.get("description", "")))
            if n > limit:
                f.add("H016", "warn", rel(root, sk), f"description {n} chars (limit {limit})",
                      "Shorter trigger-focused description; move detail into the body.")


def run(root: Path, files=None) -> tuple:
    cfg = load_config(root)
    f = Findings(cfg)
    only = None
    if files is not None:
        only = set()
        for x in files:
            p = Path(x) if Path(x).is_absolute() else root / x
            r = rel(root, p)
            if is_harness_file(root, cfg, r):
                only.add(r)
        if not only:
            return f, cfg
    check_entry_files(root, cfg, f, only)
    check_rules(root, cfg, f, only)
    check_docs(root, cfg, f, only)
    if only is None or any(is_doc(root, cfg, x) for x in only):
        check_index(root, cfg, f)
    if only is None or any(x.startswith((".harness/", ".claude/", ".cursor/", ".agents/")) or x in ENTRY for x in only):
        check_generated(root, cfg, f)
    if only is None or any(x in ENTRY or x in CODEX_ONLY_ENTRY for x in only):
        check_instruction_resolution(root, cfg, f)
    if only is None:
        check_budgets(root, cfg, f)
        check_skills(root, cfg, f)
    return f, cfg


def format_text(findings) -> str:
    if not findings:
        return "harness lint: clean"
    order = {"error": 0, "warn": 1, "info": 2}
    out = []
    for x in sorted(findings, key=lambda x: (order[x["severity"]], x["code"])):
        out.append(f"[{x['severity'].upper()}] {x['code']} {x['path']}: {x['message']}")
        if x["fix"]:
            out.append(f"    fix: {x['fix']}")
    return "\n".join(out)


def update_lock(root: Path, close: bool = False):
    """Record the ratchet baseline. Closing the transitional budgets is a separate decision.

    Until 1.5 this closed them on its own, and that is a trap in the middle of a migration:
    run halfway through, it freezes the half-migrated state as the project's permanent
    budget and removes the H019 that says the budget is provisional. Measured on a fixture:
    a restructure that opened at 1,803 entry-file lines and finished under 10 kept a budget
    of 1,713 lines forever, with nothing left to say so. The ratchet baseline is needed
    often; closing the transitional budgets happens once, in `verify`, when the plan is done.
    """
    inv = inventory.build(root, include_user=False)
    lock = {a: {"always_on_est_tokens": d["always_on_est_tokens"]} for a, d in inv["agents"].items()}
    (root / ".harness").mkdir(exist_ok=True)
    (root / ".harness/budgets.lock.json").write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    if close:
        close_transitional(root, inv)
    elif (load_config(root).get("budgets_transitional") or {}):
        print("Budgets are still the transitional ones measured at install, and stay that way: "
              "closing them freezes whatever the project measures right now as its permanent budget. "
              "Do it once, in verify, when the plan is done: lint.py --update-lock --close-transitional")
    return lock


def close_transitional(root: Path, inv: dict):
    """Tighten the opening budgets to what the project measures now, and say what moved.

    Printed, not asked: this runs inside verify, but it can also be called on its own,
    and nobody should discover afterwards that their budget moved.
    """
    cfg_path = root / ".harness/config.json"
    if not cfg_path.exists():
        return
    cfg = json.loads(read_text(cfg_path) or "{}")
    tr = cfg.get("budgets_transitional")
    if not tr:
        return
    targets = tr.get("targets", {})
    measured_tokens = max([d["always_on_est_tokens"] for d in inv["agents"].values()] or [0])
    measured_lines = 0
    for name in ENTRY:
        text = read_text(root / name) if (root / name).is_file() else ""
        if text:
            measured_lines = max(measured_lines, text.count("\n") + 1)
    new = {"always_on_tokens": max(measured_tokens, int(targets.get("always_on_tokens", 0))),
           "entry_file_lines": max(measured_lines, int(targets.get("entry_file_lines", 0)))}
    print("Transitional budgets closed:")
    for key, value in new.items():
        print(f"  {key}: {cfg['budgets'].get(key)} -> {value}")
    for agent, data in sorted(inv["agents"].items()):
        print(f"  {agent}: ~{data['always_on_est_tokens']} always-on tokens locked")
    cfg["budgets"].update(new)
    cfg.pop("budgets_transitional", None)
    cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=".")
    ap.add_argument("--files", nargs="*")
    ap.add_argument("--staged", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--update-lock", action="store_true")
    ap.add_argument("--close-transitional", action="store_true",
                    help="also tighten the opening budgets to what the project measures now (verify only)")
    a = ap.parse_args()
    root = find_project_root(Path(a.project))
    if a.update_lock:
        print(json.dumps(update_lock(root, a.close_transitional), indent=2))
        return
    files = changed_files(root, staged_only=True) if a.staged else a.files
    findings, _ = run(root, files)
    print(json.dumps(findings, indent=2) if a.json else format_text(findings))
    bad = [x for x in findings if x["severity"] == "error" or (a.strict and x["severity"] == "warn")]
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
