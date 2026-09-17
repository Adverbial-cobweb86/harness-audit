#!/usr/bin/env python3
"""Structural assertions on the inventory report. Usage: assert_inventory.py <inventory.py> <project>"""
import json
import subprocess
import sys

out = subprocess.run(["python3", sys.argv[1], "--project", sys.argv[2], "--include-user"],
                     capture_output=True, text=True)
inv = json.loads(out.stdout)

assert inv["always_on_floor"] is True, "report must declare itself a lower bound"
assert "/context" in inv["measurement_note"], "report must point at /context for the real number"

cmds = [h["command"] for h in inv["user_runtime"]["session_start_hooks"]]
assert cmds, "no SessionStart hooks collected"
long = [c for c in cmds if len(c) > 161]  # 160 chars plus the ellipsis
assert not long, f"hook command not clipped: {long}"
