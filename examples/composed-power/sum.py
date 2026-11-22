import json
import sys

request = json.load(sys.stdin)
power = sum(item["value"] for item in request["inputs"].values())
print(json.dumps({
    "protocol": request["protocol"],
    "invocation_id": request["invocation_id"],
    "outputs": {"total": {"type": "quantity", "value": power, "unit": "W"}},
}))
