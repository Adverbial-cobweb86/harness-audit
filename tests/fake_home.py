#!/usr/bin/env python3
"""Build a fake ~/.claude for the inventory test, with secrets planted everywhere.

Used by tests/smoke.sh: the inventory report is written inside the user's project and
may be committed, so the test plants a credential in an MCP env value, an MCP header,
an MCP url and a SessionStart hook command, then asserts none of them come back out.
"""
import json
import pathlib
import sys

h = pathlib.Path(sys.argv[1])
(h / ".claude/settings.json").write_text(json.dumps({
    "enabledPlugins": {"realplug@mkt": True, "ghostplug@mkt": True, "offplug@mkt": False},
    "mcpServers": {"supabase": {"command": "npx",
                               "env": {"SUPABASE_TOKEN": "SECRET-ENV-VALUE"},
                               "headers": {"Authorization": "Bearer SECRET-HEADER-VALUE"},
                               "url": "https://secret-host.example.com/mcp"}},
    "hooks": {"SessionStart": [{"hooks": [{
        "type": "command",
        "command": "node boot.mjs --api-token=SECRET-CMD-VALUE " + "pad " * 80}]}]},
}, indent=2))
(h / ".claude/agents/reviewer.md").write_text("---\nname: reviewer\ndescription: reviews diffs\n---\nbody\n")

p = h / ".claude/plugins/cache/mkt/realplug/1.0.0"
(p / "agents/planner.md").write_text("---\nname: planner\ndescription: plans work\n---\nbody\n")
(p / "hooks/hooks.json").write_text(json.dumps({"hooks": {"SessionStart": [
    {"hooks": [{"type": "command", "command": "node plugboot.mjs"}]}]}}))
(p / ".mcp.json").write_text(json.dumps({"mcpServers": {"plugmcp": {"env": {"K": "SECRET-PLUGIN-VALUE"}}}}))

(h / ".claude/plugins/marketplaces/mkt/catalog.json").write_text(
    json.dumps({"plugins": [{"name": "catalogonly"}]}))
(h / ".claude/plugins/cache/mkt/realplug/1.0.0.bak").mkdir(exist_ok=True)
