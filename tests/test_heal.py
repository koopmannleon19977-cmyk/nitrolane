"""Prove self-healing replay: a template whose element names changed is repaired in place.

1. fresh run stores the calculator template (cache: stored)
2. two template steps get the English names a translated UI would show ("Multiply by", "Equals")
3. next run: replay asks the model only for those two steps, check passes -> cache: healed
4. next run: full zero-model replay with the repaired names -> cache: hit
Usage: python test_heal.py <nitrolane.py>
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
REQ = json.loads((HERE / "cache_req_calc.json").read_text(encoding="utf-8"))
sys.path.insert(0, str(Path(sys.argv[1]).parent))
from nitrolane import _cache_path  # noqa: E402  (same identity function the tool uses)

path = _cache_path(REQ)
path.unlink(missing_ok=True)


def run() -> dict:
    subprocess.run([sys.executable, str(HERE / "reset.py"), "calc"], check=True)
    proc = subprocess.run([sys.executable, sys.argv[1]], input=json.dumps(REQ), capture_output=True,
                          text=True, encoding="utf-8", timeout=150)
    out = json.loads(proc.stdout)
    print(out.get("status"), out.get("check"), out.get("cache"), out.get("sec"), out.get("steps"))
    return out


first = run()
assert first["cache"] == "stored" and first["check"] is True, first
steps = json.loads(path.read_text(encoding="utf-8"))["steps"]
renamed = {"Multiplizieren mit": "Multiply by", "Gleich": "Equals"}
for s in steps:
    s["target_name"] = renamed.get(s.get("target_name"), s.get("target_name"))
path.write_text(json.dumps({"steps": steps}, ensure_ascii=False), encoding="utf-8")

healed = run()
assert healed["cache"] == "healed" and healed["check"] is True, healed
again = run()
assert again["cache"] == "hit" and again["check"] is True, again
print("HEAL-OK (renamed steps re-targeted by one decision each, next run zero-model)")
