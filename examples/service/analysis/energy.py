import json
import sys

request = json.load(sys.stdin)
v = {key: item["value"] for key, item in request["inputs"].items()}
if v["workers"] < 1 or v["workers"] != int(v["workers"]) or min(v["worker_power"],v["shared_power"]) < 0:
    raise ValueError("A positive integral worker count and nonnegative power values are required")
json.dump({"protocol": "closure-run/0.1", "invocation_id": request["invocation_id"], "outputs": {
    "total": {"value": v["workers"]*v["worker_power"]+v["shared_power"], "unit": "W"}}}, sys.stdout)
