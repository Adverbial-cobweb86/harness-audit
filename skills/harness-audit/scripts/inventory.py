#!/usr/bin/env python3
"""Map every harness layer per agent: always-on, conditional, on-demand.

Usage: python3 inventory.py [--project PATH] [--include-user] [--out FILE]
Loading rules reflect vendor docs as checked in Sept 2026 (see references/agents/*).
Token numbers are estimates; runtime truth comes from transcripts.py and /context.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from hlib import (HOME, as_list, docs_root, dump_json, enabled_agents, estimate_tokens, find_project_root,
                  git_environment, iter_md, load_config, parse_frontmatter, read_text, rel, safe_command)

IMPORT_RE = re.compile(r"(?<![\w`])@((?:~|\.{1,2})?/?[\w.\-/~]+)")


def strip_code(text: str) -> str:
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    return re.sub(r"`[^`\n]*`", "", text)


def item(root, path: Path, kind: str, text: str | None = None, note: str = "", **extra):
    text = read_text(path) if text is None else text
    d = {"path": rel(root, path), "kind": kind, "lines": text.count("\n") + (1 if text else 0),
         "bytes": len(text.encode("utf-8")), "est_tokens": estimate_tokens(text)}
    if note:
        d["note"] = note
    d.update(extra)
    return d


# ---------------------------------------------------------------- claude code
def claude_imports(root, path: Path, depth=0, seen=None):
    seen = seen if seen is not None else set()
    out = []
    if depth >= 4:
        return out
    for ref in IMPORT_RE.findall(strip_code(read_text(path))):
        if "/" not in ref and "." not in ref:
            continue
        target = Path(ref.replace("~", str(HOME), 1)) if ref.startswith("~") else (path.parent / ref)
        target = target.resolve()
        if target in seen or not target.is_file():
            continue
        seen.add(target)
        external = not str(target).startswith(str(root.resolve()))
        out.append(item(root, target, "import", note=f"imported by {rel(root, path)} (loads at launch)",
                        external=external))
        out.extend(claude_imports(root, target, depth + 1, seen))
    return out


def skill_listing(root, dirs, agent):
    always, hidden = [], []
    for d in dirs:
        if not d.is_dir():
            continue
        for sk in sorted(d.glob("*/SKILL.md")):
            fm, _ = parse_frontmatter(read_text(sk))
            desc = f"{fm.get('name', sk.parent.name)}: {fm.get('description', '')} {fm.get('when_to_use', '')}"
            entry = item(root, sk, "skill-description", text=desc, description_chars=len(str(fm.get("description", ""))))
            if agent == "claude-code" and fm.get("disable-model-invocation") is True:
                entry["note"] = "manual-only: description not in context"
                hidden.append(entry)
            else:
                always.append(entry)
    return always, hidden


def claude_layers(root: Path, include_user: bool):
    always, cond = [], []
    candidates = []
    for p in [root, *root.parents]:
        for name in ("CLAUDE.md", ".claude/CLAUDE.md", "CLAUDE.local.md"):
            if (p / name).is_file():
                candidates.append(p / name)
        if p == HOME or p == p.parent:
            break
    if include_user and (HOME / ".claude/CLAUDE.md").is_file():
        candidates.append(HOME / ".claude/CLAUDE.md")
    for c in candidates:
        always.append(item(root, c, "memory-file"))
        always.extend(claude_imports(root, c))
    rule_dirs = [root / ".claude/rules"] + ([HOME / ".claude/rules"] if include_user else [])
    for rd in rule_dirs:
        for r in iter_md(rd):
            fm, _ = parse_frontmatter(read_text(r))
            if as_list(fm.get("paths")):
                cond.append(item(root, r, "rule-scoped", paths=as_list(fm.get("paths"))))
            else:
                always.append(item(root, r, "rule-unscoped", note="no paths: loads every session"))
    for sub in root.rglob("CLAUDE.md"):
        if sub.parent != root and ".git" not in sub.parts and "node_modules" not in sub.parts:
            cond.append(item(root, sub, "nested-memory", note="loads when files in this dir are read"))
    enc = "-" + str(root.resolve()).strip("/").replace("/", "-").replace(".", "-")
    mem = HOME / ".claude/projects" / enc / "memory/MEMORY.md"
    if mem.is_file():
        text = "\n".join(read_text(mem).splitlines()[:200])[:25000]
        always.append(item(root, mem, "auto-memory-index", text=text, note="first 200 lines / 25KB"))
    skill_dirs = [root / ".claude/skills"] + ([HOME / ".claude/skills"] if include_user else [])
    s_always, s_hidden = skill_listing(root, skill_dirs, "claude-code")
    always.extend(s_always)
    notes = ["Plugin skills, MCP server instructions and output styles also load; confirm with /context."]
    return always, cond, s_hidden, notes


# ---------------------------------------------------------------- codex
def codex_layers(root: Path, include_user: bool, cfg: dict):
    always, cond, notes = [], [], []
    cap = int(cfg["budgets"].get("codex_project_doc_bytes", 32768))
    if include_user:
        for n in ("AGENTS.override.md", "AGENTS.md"):
            if (HOME / ".codex" / n).is_file() and read_text(HOME / ".codex" / n).strip():
                always.append(item(root, HOME / ".codex" / n, "global-instructions"))
                break
    used = 0
    for n in ("AGENTS.override.md", "AGENTS.md"):
        p = root / n
        if p.is_file() and read_text(p).strip():
            e = item(root, p, "project-doc")
            used += e["bytes"]
            if used > cap:
                e["note"] = f"TRUNCATED: project doc chain exceeds {cap} bytes"
            always.append(e)
            break
    for sub in root.rglob("AGENTS.md"):
        if sub.parent != root and ".git" not in sub.parts and "node_modules" not in sub.parts:
            cond.append(item(root, sub, "nested-project-doc", note="loads only when Codex starts inside this dir"))
    s_always, _ = skill_listing(root, [root / ".agents/skills", root / ".codex/skills"] +
                                ([HOME / ".agents/skills", HOME / ".codex/skills"] if include_user else []), "codex")
    always.extend(s_always)
    notes.append(f"Codex caps the combined AGENTS.md chain at project_doc_max_bytes ({cap} bytes) and truncates silently.")
    notes.append("Codex has no @import: pointers must be plain paths the agent reads on demand.")
    return always, cond, [], notes


# ---------------------------------------------------------------- cursor
def cursor_layers(root: Path, include_user: bool):
    always, cond, notes = [], [], []
    if (root / "AGENTS.md").is_file():
        always.append(item(root, root / "AGENTS.md", "agents-md"))
    if (root / ".cursorrules").is_file():
        always.append(item(root, root / ".cursorrules", "legacy-cursorrules", note="deprecated: migrate to .cursor/rules"))
    for r in iter_md(root / ".cursor/rules"):
        text = read_text(r)
        if r.suffix != ".mdc":
            cond.append(item(root, r, "ignored-rule", note=".md in .cursor/rules is ignored; use .mdc"))
            continue
        fm, _ = parse_frontmatter(text)
        if fm.get("alwaysApply") is True:
            always.append(item(root, r, "rule-always"))
        elif as_list(fm.get("globs")):
            cond.append(item(root, r, "rule-globs", globs=as_list(fm.get("globs"))))
        elif fm.get("description"):
            always.append(item(root, r, "rule-agent-requested-description", text=str(fm.get("description"))))
            cond.append(item(root, r, "rule-agent-requested"))
        else:
            cond.append(item(root, r, "rule-manual"))
    s_always, _ = skill_listing(root, [root / ".cursor/skills"] + ([HOME / ".cursor/skills"] if include_user else []), "cursor")
    always.extend(s_always)
    notes.append("User Rules live in Cursor settings (not on disk) and always apply: review them manually.")
    return always, cond, [], notes


# ---------------------------------------------------------------- antigravity
def antigravity_layers(root: Path, include_user: bool):
    always, cond, notes = [], [], []
    if include_user and (HOME / ".gemini/GEMINI.md").is_file():
        always.append(item(root, HOME / ".gemini/GEMINI.md", "global-context"))
    for n in ("GEMINI.md", "AGENTS.md"):
        if (root / n).is_file():
            always.append(item(root, root / n, "context-file"))
    for r in iter_md(root / ".agents/rules"):
        always.append(item(root, r, "workspace-rule", note="assumed always-on; verify with agy inspect"))
    s_always, _ = skill_listing(root, [root / ".agents/skills"], "antigravity")
    always.extend(s_always)
    notes.append("Antigravity reads GEMINI.md literally (no @import expansion). Legacy Gemini CLI did expand @imports.")
    notes.append("If GEMINI.md and AGENTS.md both exist, their content is paid twice: keep one canonical.")
    return always, cond, [], notes


# ---------------------------------------------------------------- user runtime
# Plugins, custom agents, MCP servers and SessionStart hook output are always-on
# costs that never appear as files in the project. They are listed here so the
# baseline is not read as the whole story. Nothing in this section is executed,
# and no env value, header, URL or credential is ever written out.
SETTINGS_FILES = (".claude/settings.json", ".claude/settings.local.json", ".claude.json")


def _json(path: Path) -> dict:
    try:
        data = json.loads(read_text(path) or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def user_settings():
    return [(p, _json(p)) for p in (HOME / f for f in SETTINGS_FILES) if p.is_file()]


def plugin_dir(marketplace: str, name: str) -> Path | None:
    """Resolve an enabled plugin to its folder on disk.

    ~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/ is the installed copy.
    ~/.claude/plugins/marketplaces/ holds catalogs of plugins that are NOT installed,
    and *.bak copies are leftovers: neither may be counted.
    """
    base = HOME / ".claude/plugins/cache" / marketplace / name
    if not base.is_dir():
        return None
    versions = sorted((d for d in base.iterdir() if d.is_dir() and not d.name.endswith(".bak")),
                      key=lambda d: d.name)
    return versions[-1] if versions else (base if (base / ".claude-plugin").is_dir() else None)


def enabled_plugins():
    """[(id, marketplace, name, dir or None)] for every plugin switched on in settings."""
    out, seen = [], set()
    for _, data in user_settings():
        for pid, on in (data.get("enabledPlugins") or {}).items():
            if on is not True or pid in seen:
                continue
            seen.add(pid)
            name, _, marketplace = str(pid).partition("@")
            out.append((pid, marketplace, name, plugin_dir(marketplace, name)))
    return sorted(out)


def mcp_servers(plugins):
    """Server NAMES only. Values carry env, headers and tokens and are never read."""
    found = []
    for path, data in user_settings():
        for name in (data.get("mcpServers") or {}):
            found.append({"name": name, "source": rel(HOME, path)})
    for pid, _, _, d in plugins:
        if d and (d / ".mcp.json").is_file():
            for name in (_json(d / ".mcp.json").get("mcpServers") or {}):
                found.append({"name": name, "source": f"plugin:{pid}"})
    return found


def custom_agents(root: Path, plugins):
    out = []
    for p in sorted(iter_md(HOME / ".claude/agents")):
        fm, _ = parse_frontmatter(read_text(p))
        desc = f"{fm.get('name', p.stem)}: {fm.get('description', '')}"
        out.append(item(root, p, "agent-description", text=desc, source="user"))
    for pid, _, _, d in plugins:
        if not d:
            continue
        for p in sorted(iter_md(d / "agents")):
            fm, _ = parse_frontmatter(read_text(p))
            desc = f"{fm.get('name', p.stem)}: {fm.get('description', '')}"
            out.append(item(root, p, "agent-description", text=desc, source=f"plugin:{pid}"))
    return out


def session_start_hooks(plugins):
    """SessionStart commands whose stdout is injected into every session. Never run."""
    out = []

    def collect(data: dict, source: str):
        for group in (data.get("hooks") or {}).get("SessionStart") or []:
            for h in group.get("hooks") or []:
                if h.get("command"):
                    out.append({"command": safe_command(h["command"]), "source": source})

    for path, data in user_settings():
        collect(data, rel(HOME, path))
    for pid, _, _, d in plugins:
        if d and (d / "hooks/hooks.json").is_file():
            collect(_json(d / "hooks/hooks.json"), f"plugin:{pid}")
    return out


def user_runtime(root: Path):
    plugins = enabled_plugins()
    agents = custom_agents(root, plugins)
    hooks = session_start_hooks(plugins)
    servers = mcp_servers(plugins)
    return {
        "plugins": [{"id": pid, "installed": bool(d), "path": str(d) if d else None} for pid, _, _, d in plugins],
        "agents": agents,
        "agents_est_tokens": sum(a["est_tokens"] for a in agents),
        "mcp_servers": servers,
        "session_start_hooks": hooks,
        "notes": [
            f"{len(plugins)} enabled plugin(s), {len(agents)} custom agent(s), {len(servers)} MCP server(s) and "
            f"{len(hooks)} SessionStart hook(s) also consume always-on context.",
            "Plugin skills, MCP tool schemas and SessionStart hook output are NOT counted in est_tokens: "
            "their size is only known at runtime. Read the total from /context in a fresh session.",
            "Hooks are listed, never executed. MCP entries are names only, with no env, header, URL or token.",
        ],
    }


def on_demand(root: Path, cfg: dict):
    droot = docs_root(root, cfg)
    files = [item(root, p, "doc") for p in iter_md(droot)]
    vault = cfg.get("vault") or {}
    vfiles = []
    if vault.get("enabled") and vault.get("path"):
        vp = Path(str(vault["path"]).replace("~", str(HOME), 1)).resolve()
        if vp != droot and not str(droot).startswith(str(vp)):
            vfiles = [item(root, p, "vault-note") for p in iter_md(vp)]
        elif vp != droot:
            vfiles = [item(root, p, "vault-note") for p in iter_md(vp) if not str(p.resolve()).startswith(str(droot))]
    return files, vfiles


def build(root: Path, include_user: bool):
    cfg = load_config(root)
    agents = enabled_agents(root, cfg)
    report = {"project": str(root), "agents": {}, "include_user": include_user}
    for a in agents:
        if a == "claude-code":
            al, co, hid, notes = claude_layers(root, include_user)
        elif a == "codex":
            al, co, hid, notes = codex_layers(root, include_user, cfg)
        elif a == "cursor":
            al, co, hid, notes = cursor_layers(root, include_user)
        else:
            al, co, hid, notes = antigravity_layers(root, include_user)
        report["agents"][a] = {
            "always_on": al, "conditional": co, "manual_only": hid, "notes": notes,
            "always_on_est_tokens": sum(x["est_tokens"] for x in al),
            "conditional_est_tokens": sum(x["est_tokens"] for x in co),
        }
    if include_user:
        report["user_runtime"] = user_runtime(root)
    report["always_on_floor"] = True
    report["git_environment"] = git_environment()
    report["measurement_note"] = (
        "est_tokens counts files only and is a LOWER BOUND on always-on context. Plugins, MCP servers, "
        "custom agents and SessionStart hook output are not measurable from disk. The authoritative "
        "number is /context in a fresh session.")
    docs, vault = on_demand(root, cfg)
    report["on_demand"] = {"docs_count": len(docs), "docs_est_tokens": sum(x["est_tokens"] for x in docs),
                           "vault_count": len(vault), "vault_est_tokens": sum(x["est_tokens"] for x in vault),
                           "largest_docs": sorted(docs + vault, key=lambda x: -x["est_tokens"])[:10]}
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=".")
    ap.add_argument("--include-user", action="store_true", help="also read ~/.claude, ~/.codex, ~/.gemini")
    ap.add_argument("--out")
    a = ap.parse_args()
    root = find_project_root(Path(a.project))
    print(dump_json(build(root, a.include_user), Path(a.out) if a.out else None))


if __name__ == "__main__":
    main()
