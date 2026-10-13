"""Replace the calculation; keep the language-neutral JSON boundary."""
import json
import sys

request = json.load(sys.stdin)
result = request["inputs"]["allocation"]["value"]
json.dump({"protocol": "closure-run/0.1", "invocation_id": request["invocation_id"],
           "outputs": {"used": {"value": result}}}, sys.stdout)
