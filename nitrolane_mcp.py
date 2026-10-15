"""nitrolane MCP server: exposes nitrolane_run and nitrolane_doctor over stdio (NDJSON JSON-RPC).

Run with the venv python next to nitrolane.py, e.g.:
    vendor/arc-cua-windows/.venv/Scripts/python.exe nitrolane_mcp.py

Subtasks run inside this long-lived process: the arc-cua stack and the warm-Chrome lookup are
loaded once instead of paying a fresh interpreter start per call.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import nitrolane as lane  # noqa: E402

# Protocol revisions this server speaks; the client's choice wins when we know it.
PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")

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
    # Anything the lane or its backends print must not reach stdout: that is the JSON-RPC channel.
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        if args == ["doctor"]:
            lane._doctor([])
            return buf.getvalue()
        out, _ = lane.run(payload)
    return json.dumps(out, ensure_ascii=False, indent=1)


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
                asked = (req.get("params") or {}).get("protocolVersion")
                _reply(mid, {"protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
                             "capabilities": {"tools": {}},
                             "serverInfo": {"name": "nitrolane", "version": lane.__version__}})
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
