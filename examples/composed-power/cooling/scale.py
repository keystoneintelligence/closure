import json
import sys

request = json.load(sys.stdin)
power = 2 * request["inputs"]["reference"]["value"]
print(json.dumps({
    "protocol": request["protocol"],
    "invocation_id": request["invocation_id"],
    "outputs": {"demand": {"type": "quantity", "value": power, "unit": "W"}},
}))
