"""An ordinary Python program implementing the language-neutral runner protocol."""
import json
import sys

request = json.load(sys.stdin)
total = request["inputs"]["payload"]["value"] + request["inputs"]["base"]["value"]
json.dump({"protocol": "closure-run/0.1", "invocation_id": request["invocation_id"],
           "outputs": {"total": {"value": total, "unit": "W"}}}, sys.stdout)
