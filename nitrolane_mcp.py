"""nitrolane MCP server: exposes nitrolane_run and nitrolane_doctor over stdio (NDJSON JSON-RPC).

Run with the venv python next to nitrolane.py, e.g.:
    vendor/arc-cua-windows/.venv/Scripts/python.exe nitrolane_mcp.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
LANE = HERE / "nitrolane.py"

TOOLS = [
    {"name": "nitrolane_run",
     "description": "Run one bounded, verified browser or Windows-desktop subtask at decision-model speed. "
                    "Pass the nitrolane request object: {target, url|app, subtask{goal, inputs, verification[], "
                    "constraints[]}, check, extract?, cache?, transitions?, provider?}. Returns the result JSON "
                    "(status SUBTASK_COMPLETE | NEEDS_INPUT | NEEDS_AGENT | BLOCKED, steps, independent check).",
     "inputSchema": {"type": "object", "properties": {"request": {"type": "object"}}, "required": ["request"]}},
    {"name": "nitrolane_doctor",
     "description": "Check whether this machine can run nitrolane (Chrome, CDP, API key presence, UIA).",
     "inputSchema": {"type": "object", "properties": {}}},
]


def _run_lane(args: list[str], payload: dict | None) -> str:
    proc = subprocess.run([sys.executable, str(LANE), *args],
                          input=json.dumps(payload) if payload is not None else None,
                          capture_output=True, text=True, encoding="utf-8", timeout=600)
    return proc.stdout or proc.stderr[-1000:]


def _reply(mid, result=None, error=None) -> None:
    msg: dict = {"jsonrpc": "2.0", "id": mid}
    msg.update({"error": error} if error else {"result": result})
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> int:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        mid, method = req.get("id"), req.get("method", "")
        if mid is None:  # notification (e.g. notifications/initialized)
            continue
        try:
            if method == "initialize":
                _reply(mid, {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                             "serverInfo": {"name": "nitrolane", "version": "0.2.0"}})
            elif method == "ping":
                _reply(mid, {})
            elif method == "tools/list":
                _reply(mid, {"tools": TOOLS})
            elif method == "tools/call":
                params = req.get("params") or {}
                name, arguments = params.get("name"), params.get("arguments") or {}
                if name == "nitrolane_run":
                    text = _run_lane([], arguments["request"])
                elif name == "nitrolane_doctor":
                    text = _run_lane(["doctor"], None)
                else:
                    raise ValueError(f"unknown tool {name!r}")
                _reply(mid, {"content": [{"type": "text", "text": text}]})
            else:
                _reply(mid, error={"code": -32601, "message": f"method not found: {method}"})
        except Exception as exc:  # one bad call must not kill the server
            _reply(mid, error={"code": -32000, "message": f"{type(exc).__name__}: {exc}"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
