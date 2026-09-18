#!/usr/bin/env python3
"""Assertions on the dirty survey. Usage: assert_dirty.py <submodule=yes|submodule=skipped: ...> < survey.json"""
import json
import sys

d = json.load(sys.stdin)
sub_state = sys.argv[1] if len(sys.argv) > 1 else "submodule=skipped"

assert d["clean"] is False and d["read_only"] is True, d
assert d["cache_total"] == 1 and d["cache"][0]["files"] == 12, d["cache"]
assert d["cache"][0]["suggested_gitignore"] == "node_modules/", d["cache"]
assert d["modified_total"] == 1 and d["modified"][0]["added"] == 7, d["modified"]
assert d["modified"][0]["age_days"] is not None, d["modified"]
assert d["untracked_total"] == 1 and d["untracked"][0]["size_bytes"] == 4096, d["untracked"]
assert d["stashes_total"] == 1, d["stashes"]
st = d["stashes"][0]
assert st["ref"] == "stash@{0}" and st["files"] == 2 and st["added"] == 4, st
assert st["age_days"] is not None and st["date"], st
assert st["evidence_command"] == "git stash show -p stash@{0}", st
assert len(st["subject"]) <= 81, st

# discard is offered last and marked irreversible; it is never the first option
assert "discard" in d["options"][-1] and "irreversible" in d["options"][-1], d["options"]
assert not any("discard" in o for o in d["options"][:-1]), d["options"]
assert "git clean" in d["never_run_by_this_skill"] and "git stash" in d["never_run_by_this_skill"], d

if sub_state == "submodule=yes":
    assert d["submodules_total"] == 1, d["submodules"]
    s = d["submodules"][0]
    assert s["path"] == "sub" and s["recorded"] != s["current"], s
    assert s["commits"] and "v9.9.9" in s["tags"], s
    assert s["evidence_command"].startswith("git -C sub log --oneline"), s
