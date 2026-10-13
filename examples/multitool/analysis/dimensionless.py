"""A plain Python analysis consuming Blender-produced geometry."""
import json
import sys
request = json.load(sys.stdin)
v = {k: value["value"] for k, value in request["inputs"].items()}
reynolds = v["lid_speed"] * v["length"] / v["viscosity"]
json.dump({"protocol": "closure-run/0.1", "invocation_id": request["invocation_id"],
           "outputs": {"reynolds": {"value": reynolds}}}, sys.stdout, allow_nan=False)
