"""Minimal stdio MCP client for the head-to-head: start a server, list or call tools, time calls."""
import json, queue, subprocess, sys, threading, time


class Client:
    def __init__(self, argv, init_timeout=180):
        self.p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  text=True, encoding="utf-8", bufsize=1, shell=isinstance(argv, str))
        self.q = queue.Queue()
        threading.Thread(target=lambda: [self.q.put(l) for l in self.p.stdout], daemon=True).start()
        self.i = 0
        self.call_raw("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                     "clientInfo": {"name": "h2h", "version": "0"}}, init_timeout)
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        self.p.stdin.flush()

    def call_raw(self, method, params, timeout=60):
        self.i += 1
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.i, "method": method, "params": params}) + "\n")
        self.p.stdin.flush()
        end = time.monotonic() + timeout
        while True:
            line = self.q.get(timeout=max(0.01, end - time.monotonic()))
            try:
                m = json.loads(line)
            except ValueError:
                continue
            if m.get("id") == self.i:
                return m

    def tool(self, name, args, timeout=60):
        t = time.perf_counter()
        r = self.call_raw("tools/call", {"name": name, "arguments": args}, timeout)
        return round(time.perf_counter() - t, 3), r

    def tools(self):
        return self.call_raw("tools/list", {})["result"]["tools"]

    def close(self):
        self.p.kill()


if __name__ == "__main__":
    c = Client(sys.argv[1:] if len(sys.argv) > 2 else sys.argv[1])
    for t in c.tools():
        print(t["name"], "|", (t.get("description") or "")[:110].replace("\n", " "), "|", list((t.get("inputSchema") or {}).get("properties", {}))[:8])
    c.close()
