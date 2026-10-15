"""Wire-format test for nitrolane's ChatChoiceTransport against a local stub chat endpoint."""
import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

spec = importlib.util.spec_from_file_location("nitrolane", sys.argv[1])
lane = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lane)


class Stub(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        payload = json.loads(body["messages"][1]["content"])
        answers = {q: {"choice": next(iter(d["criteria"])), "confidence": 0.9} for q, d in payload["questions"].items()}
        out = {"choices": [{"message": {"content": json.dumps({"answers": answers})}}]}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


server = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
threading.Thread(target=server.serve_forever, daemon=True).start()
transport = lane.ChatChoiceTransport("stub-model", base_url=f"http://127.0.0.1:{server.server_port}/v1", api_key="x")
result = transport.ask({"goal": "test"}, {"operation": {"criteria": {"CLICK": "click", "WAIT": "wait"}},
                                          "click_target": {"criteria": {"w1": "OK button"}}})
assert result["answers"]["operation"]["choice"] == "CLICK", result
assert result["answers"]["click_target"]["confidence"] == 0.9, result
policy = lane._policy({"provider": {"name": "chat", "model": "stub-model", "base_url": "http://127.0.0.1:1/v1"}})
assert type(policy).__name__ == "ChoicePolicy"
print("CHAT-TRANSPORT-OK")
server.shutdown()
