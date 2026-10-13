"""Ordinary Python bridge: isolate Blender diagnostics from the JSON protocol."""
import json
import subprocess
import sys
from pathlib import Path

request = json.load(sys.stdin)
output = Path(request["output_dir"])
request_file = output / "blender-request.json"
result_file = output / "blender-result.json"
request_file.write_text(json.dumps(request), encoding="utf-8")
executable = request["tools"]["executables"]["blender"]["path"]
subprocess.run([executable, "--background", "--factory-startup", "--disable-autoexec",
                "--python-exit-code", "13", "--python", "analysis/blender_scene.py", "--",
                str(request_file), str(result_file)], check=True, stdout=sys.stderr, stderr=sys.stderr, timeout=100)
response = json.loads(result_file.read_text(encoding="utf-8"))
assert response["invocation_id"] == request["invocation_id"]
json.dump(response, sys.stdout, allow_nan=False)
