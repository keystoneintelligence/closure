"""Standalone JSON protocol example: no dependency on Closure or a CAD tool."""
import csv
import json
import sys
from pathlib import Path

request = json.load(sys.stdin)
v = {key: item["value"] for key, item in request["inputs"].items()}
if v["workers"] < 1 or v["workers"] != int(v["workers"]) or v["per_worker"] <= 0 or v["arrival"] < 0:
    raise ValueError("Nonnegative traffic, a positive integral worker count and positive throughput are required")
throughput = v["workers"] * v["per_worker"]
utilization = 100 * v["arrival"] / throughput
detail = Path(request["output_dir"]) / "capacity.csv"
with detail.open("w", newline="", encoding="utf-8") as stream:
    writer = csv.writer(stream)
    writer.writerow(["arrival_per_s", "workers", "capacity_per_s", "headroom_percent"])
    writer.writerow([v["arrival"], v["workers"], throughput, 100-utilization])
json.dump({"protocol": "closure-run/0.1", "invocation_id": request["invocation_id"], "outputs": {
    "throughput": {"value": throughput, "unit": "1/s"},
    "headroom": {"value": 100-utilization, "unit": "percent"},
    "utilization": {"value": utilization, "unit": "percent"},
    "detail": {"path": str(detail), "media_type": "text/csv"}}}, sys.stdout)
