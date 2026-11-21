import json
import sys

request = json.load(sys.stdin)
power = request["inputs"]["reference"]["value"]
print(json.dumps({
    "protocol": request["protocol"],
    "invocation_id": request["invocation_id"],
    "outputs": {"power": {"type": "quantity", "value": power, "unit": "W"}},
}))
