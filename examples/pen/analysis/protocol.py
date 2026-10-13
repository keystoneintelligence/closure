"""Tiny runner helper: the analyses have no dependency on Closure itself."""
import json
import sys
from pathlib import Path


def read():
    request = json.load(sys.stdin)
    values = {name: item.get("value", item.get("path")) for name, item in request["inputs"].items()}
    return request, values, Path(request["output_dir"])


def quantity(value, unit):
    return {"value": value, "unit": unit}


def scalar(value):
    return {"value": value}


def artifact(path, media_type="application/json"):
    return {"path": str(path), "media_type": media_type}


def write(request, outputs):
    json.dump({"protocol": "closure-run/0.1", "invocation_id": request["invocation_id"], "outputs": outputs}, sys.stdout, allow_nan=False)
