"""Shared helpers for harness-audit scripts. Python 3.9+, standard library only."""
from __future__ import annotations

import fnmatch
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

HOME = Path.home()
AGENTS = ("claude-code", "codex", "cursor", "antigravity")
ENTRY_FILES = ("CLAUDE.md", "CLAUDE.local.md", "AGENTS.md", "AGENTS.override.md", "GEMINI.md")
GENERATED_MARK = "<!-- harness:generated"

DEFAULT_CONFIG = {
    "version": 1,
    "agents": "auto",
    "docs_dir": "docs",
    "vault": {"enabled": False, "path": None, "project_folder": None, "topology": None},
    "budgets": {
        "always_on_tokens": 5000,
        "entry_file_lines": 120,
        "codex_project_doc_bytes": 32768,
        "rule_tokens": 1500,
        "skill_description_chars": 400,
        "doc_tokens_warn": 8000,
        "stale_days": 120,
    },
    "ratchet": True,
    "required_frontmatter": ["description", "updated", "status"],
    "allowed_status": ["active", "draft", "superseded", "archived", "completed"],
    "index": {"file": "index.md", "exclude": ["raw/**", "index.md", "log.md", "_templates/**", "_attachments/**"]},
    "log": {"file": "log.md"},
    "placement": {
        "decisions": "Architecture decisions (ADR), NNNN-title.md, never deleted, mark superseded",
        "plans/active": "Work in progress plans",
        "plans/completed": "Finished plans",
        "runbooks": "Operational procedures a human or agent follows",
        "references": "Long reference material, read on demand only",
        "architecture": "System maps and domain boundaries",
        "product": "Product specs and requirements",
        "raw": "Immutable sources (clippings, transcripts). Read-only for agents",
    },
    "rules_source": ".harness/rules",
    "skills_source": ".harness/skills",
}


def docs_root(root: Path, cfg: dict) -> Path:
    """docs_dir may be relative to the repo or an absolute/~ path into an Obsidian vault."""
    d = str(cfg.get("docs_dir", "docs"))
    p = Path(d.replace("~", str(HOME), 1)) if d.startswith("~") else Path(d)
    return (p if p.is_absolute() else root / p).resolve()


def doc_rel(root: Path, cfg: dict, p: Path) -> str:
    """Path relative to the docs root (used for placement, exclude and index grouping)."""
    try:
        return Path(p).resolve().relative_to(docs_root(root, cfg)).as_posix()
    except ValueError:
        return ""


def index_path(root: Path, cfg: dict) -> Path:
    return docs_root(root, cfg) / cfg["index"].get("file", "index.md")


def log_path(root: Path, cfg: dict) -> Path:
    return docs_root(root, cfg) / cfg["log"].get("file", "log.md")


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token). Runtime numbers come from transcripts."""
    return max(0, round(len(text) / 4))


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeError):
        return ""


def find_project_root(start: Path) -> Path:
    cur = start.resolve()
    for p in [cur, *cur.parents]:
        if (p / ".git").exists() or (p / ".harness").is_dir():
            return p
    return cur


def load_config(root: Path) -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    path = root / ".harness" / "config.json"
    if path.exists():
        user = json.loads(read_text(path) or "{}")
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    return cfg


# ---------------------------------------------------------------- frontmatter
FM_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(\n|\Z)", re.S)


def _scalar(v: str):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    low = v.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        return [_scalar(x) for x in inner.split(",") if x.strip()] if inner else []
    return v


def parse_frontmatter(text: str):
    """Minimal YAML subset: key: value, inline lists, block lists. Returns (dict, body)."""
    m = FM_RE.match(text)
    if not m:
        return {}, text
    data, key = {}, None
    for raw in m.group(1).splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        item = re.match(r"^\s*-\s+(.*)$", raw)
        if item and key is not None:
            if not isinstance(data.get(key), list):
                data[key] = []
            data[key].append(_scalar(item.group(1)))
            continue
        kv = re.match(r"^([A-Za-z0-9_\-]+)\s*:\s*(.*)$", raw)
        if kv:
            key, val = kv.group(1), kv.group(2)
            data[key] = _scalar(val) if val.strip() else []
    return data, text[m.end():]


def as_list(v) -> list:
    if v is None or v == "" or v == []:
        return []
    if isinstance(v, list):
        return [str(x) for x in v]
    return [x.strip() for x in str(v).split(",") if x.strip()]


# ---------------------------------------------------------------- files
def rel(root: Path, p: Path) -> str:
    try:
        return p.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(p)


def match_any(path: str, patterns) -> bool:
    return any(fnmatch.fnmatch(path, pat) for pat in patterns)


def iter_md(base: Path, exclude=(), root: Path | None = None):
    """Yield .md/.mdc under base. exclude globs are matched relative to base."""
    if not base.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules", ".obsidian", ".trash")]
        for f in filenames:
            if f.endswith((".md", ".mdc")):
                p = Path(dirpath) / f
                if not match_any(p.relative_to(base).as_posix(), exclude):
                    yield p


# ---------------------------------------------------------------- git
# Every read below is parsed (porcelain, --oneline, rev-parse, ls-files, status
# --short), so a shell wrapper that "improves" git output silently breaks the
# parser. In the second pilot an rtk wrapper on PATH turned
# `git worktree list --porcelain` back into the human format and the audit read
# garbage. So: call the real binary, and say so when PATH points elsewhere.
PATH_GIT = shutil.which("git")
GIT_BIN = "/usr/bin/git" if os.access("/usr/bin/git", os.X_OK) else (PATH_GIT or "git")


def git_environment() -> dict:
    """What git we actually run, and whether something on PATH is shadowing it."""
    return {
        "git_bin": GIT_BIN,
        "path_git": PATH_GIT,
        "wrapper_suspected": bool(PATH_GIT and os.path.realpath(PATH_GIT) != os.path.realpath(GIT_BIN)),
        "note": ("A different git is first on PATH; harness scripts call the real binary because "
                 "they parse machine-readable output." if PATH_GIT and
                 os.path.realpath(PATH_GIT) != os.path.realpath(GIT_BIN) else ""),
    }


def git(root: Path, *args) -> str:
    try:
        out = subprocess.run([GIT_BIN, "-C", str(root), *args], capture_output=True, text=True, timeout=20)
        return out.stdout if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def upstream_state(root: Path) -> dict:
    """How far the working branch is from the branch it should be measured against.

    A baseline read from a branch 48 commits behind the remote measures a file that
    no longer exists: that is what happened in the second pilot, and it only surfaced
    mid-apply. @{upstream} is the right reference when it is set; a working branch
    without one still has origin/HEAD to compare against.
    """
    state = {"upstream": None, "reference": None, "behind": 0, "ahead": 0, "diverged": False}
    ref = git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}").strip()
    if ref:
        state["upstream"] = ref
    else:
        head = git(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD").strip()
        ref = head or ""
    if not ref:
        return state
    state["reference"] = ref
    counts = git(root, "rev-list", "--left-right", "--count", f"{ref}...HEAD").split()
    if len(counts) == 2:
        state["behind"], state["ahead"] = int(counts[0]), int(counts[1])
        state["diverged"] = state["behind"] > 0 and state["ahead"] > 0
    return state


def changed_files(root: Path, staged_only=False) -> list:
    if staged_only:
        out = git(root, "diff", "--cached", "--name-only", "--diff-filter=ACMR")
        return [l for l in out.splitlines() if l]
    out = git(root, "status", "--porcelain", "--untracked-files=all")
    files = []
    for line in out.splitlines():
        path = line[3:].split(" -> ")[-1].strip().strip('"')
        if path:
            files.append(path)
    return files


def detect_agents(root: Path) -> list:
    found = []
    if (root / "CLAUDE.md").exists() or (root / ".claude").is_dir():
        found.append("claude-code")
    if (root / "AGENTS.md").exists() or (root / ".codex").is_dir():
        found.append("codex")
    if (root / ".cursor").is_dir() or (root / ".cursorrules").exists():
        found.append("cursor")
    if (root / "GEMINI.md").exists() or (root / ".agents").is_dir() or (root / ".gemini").is_dir():
        found.append("antigravity")
    return found


def enabled_agents(root: Path, cfg: dict) -> list:
    a = cfg.get("agents", "auto")
    if a == "auto" or not a:
        return detect_agents(root) or ["claude-code"]
    return [x for x in a if x in AGENTS]


def dump_json(data, path: Path | None):
    text = json.dumps(data, indent=2, ensure_ascii=False)
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    return text


# ---------------------------------------------------------------- redaction
SECRET_KV_RE = re.compile(
    r"\b([A-Za-z0-9_\-]*(?:token|key|secret|password|passwd|pwd|apikey|auth)[A-Za-z0-9_\-]*)"
    r"(\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|\S+)", re.I)
SECRET_FLAG_RE = re.compile(
    r"(--?[A-Za-z0-9_\-]*(?:token|key|secret|password|passwd|pwd|apikey|auth)[A-Za-z0-9_\-]*)"
    r"(\s+)(\"[^\"]*\"|'[^']*'|\S+)", re.I)


def mask_secrets(text: str) -> str:
    """Replace the value of any token=/key=/secret=/password= pair with ***.

    The inventory is written into the user's project and may be committed, so no
    credential picked up from a hook command may ever reach the report.
    """
    out = SECRET_KV_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}***", text or "")
    return SECRET_FLAG_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}***", out)


def safe_command(text: str, limit: int = 160) -> str:
    """Masked and clipped form of a hook command. Never executed, only described."""
    out = mask_secrets(" ".join(str(text or "").split()))
    return out if len(out) <= limit else out[:limit] + "…"
