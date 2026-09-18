#!/usr/bin/env python3
"""Build an unclean working tree for the dirty-survey test. Usage: dirty_fixture.py <repo>

Plants a secret in a stash message and in an untracked filename, because both are
user-written text that reaches a report living in .harness/reports/.
Prints "submodule=yes" or "submodule=skipped: <reason>" so the smoke test can tell a
real result from an environment that refuses file-protocol submodules.
"""
import os
import pathlib
import subprocess
import sys

GIT = "/usr/bin/git" if os.access("/usr/bin/git", os.X_OK) else "git"
repo = pathlib.Path(sys.argv[1])


def run(*args, cwd=repo, check=True):
    p = subprocess.run([GIT, "-C", str(cwd), *args], capture_output=True, text=True)
    if check and p.returncode != 0:
        raise SystemExit(f"{' '.join(args)}: {p.stderr.strip()}")
    return p


# a stash: two files, message carrying a secret
(repo / "stashed_a.txt").write_text("one\ntwo\nthree\n")
(repo / "stashed_b.txt").write_text("four\n")
run("add", "-A")
run("stash", "push", "-m", "wip deploy with token=SECRET-STASH-VALUE and more text")

# cache: many untracked files under node_modules/
cache = repo / "node_modules/pkg"
cache.mkdir(parents=True)
for i in range(12):
    (cache / f"f{i}.js").write_text("x" * 500)

# a modified tracked file
target = repo / "CLAUDE.md"
target.write_text(target.read_text() + "\n".join(f"- added line {i}" for i in range(7)) + "\n")

# a plain untracked file whose NAME carries a secret
(repo / "dump-api_key=SECRET-NAME-VALUE.txt").write_text("y" * 4096)

# a submodule whose pointer is ahead of what the parent records
sub = repo.parent / "subrepo"
sub.mkdir(parents=True, exist_ok=True)
subprocess.run([GIT, "init", "-q", str(sub)], check=True)
run("config", "user.email", "t@t", cwd=sub)
run("config", "user.name", "t", cwd=sub)
(sub / "lib.txt").write_text("v1\n")
run("add", "-A", cwd=sub)
run("commit", "-qm", "base", cwd=sub)

add = subprocess.run([GIT, "-C", str(repo), "-c", "protocol.file.allow=always",
                      "submodule", "add", "-q", str(sub), "sub"], capture_output=True, text=True)
if add.returncode != 0:
    print("submodule=skipped: " + (add.stderr.strip().splitlines() or ["submodule add refused"])[-1])
else:
    run("commit", "-qm", "add submodule")
    (sub / "lib.txt").write_text("v2\n")
    run("add", "-A", cwd=sub)
    run("commit", "-qm", "release work with token=SECRET-COMMIT-VALUE", cwd=sub)
    run("tag", "v9.9.9", cwd=sub)
    inner = repo / "sub"
    run("fetch", "-q", "origin", cwd=inner, check=False)
    run("pull", "-q", "--ff-only", "origin", "HEAD", cwd=inner, check=False)
    if run("rev-parse", "HEAD", cwd=inner).stdout.strip() == run("rev-parse", "HEAD", cwd=sub).stdout.strip():
        print("submodule=yes")
    else:
        print("submodule=skipped: could not advance the submodule pointer in this environment")
