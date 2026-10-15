"""Smoke test for nitrolane_mcp.py: initialize, list tools, call doctor — no UI touched."""
import json
import subprocess
import sys

proc = subprocess.Popen([sys.executable, sys.argv[1]], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        text=True, encoding="utf-8")


def call(mid, method, params=None):
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}}) + "\n")
    proc.stdin.flush()
    return json.loads(proc.stdout.readline())


init = call(1, "initialize")
assert init["result"]["serverInfo"]["name"] == "nitrolane", init
proc.stdin.write('{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
proc.stdin.flush()
tools = call(2, "tools/list")
assert [t["name"] for t in tools["result"]["tools"]] == ["nitrolane_run", "nitrolane_doctor"], tools
doctor = call(3, "tools/call", {"name": "nitrolane_doctor", "arguments": {}})
report = json.loads(doctor["result"]["content"][0]["text"])
assert report["ok"] is True and report["typesafe_key"] is True, report
proc.stdin.close()
proc.wait(timeout=10)
print("MCP-OK", {k: report[k] for k in ("ok", "chrome_cdp_alive", "uia_windows")})
