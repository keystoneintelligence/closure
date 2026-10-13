"""Windows/WSL bridge; solver work stays inside the frozen execution snapshot."""
import json
import subprocess
import sys
from pathlib import Path

request = json.load(sys.stdin)
output = Path(request["output_dir"])
executable = request["tools"]["executables"]["wsl"]["path"]
distribution = request["settings"].get("distribution", "Ubuntu")
prefix = [executable, "-d", distribution, "--exec"]
def linux_path(path):
    return subprocess.check_output(prefix + ["wslpath", "-a", str(Path(path).resolve())], text=True, timeout=20).strip()

# The Linux worker receives Linux paths. Typed input values remain identical.
worker_request = dict(request, output_dir=linux_path(output))
worker_request["case_source"] = linux_path("case")
request_file = output / "foam-request.json"
request_file.write_text(json.dumps(worker_request), encoding="utf-8")
worker = linux_path("analysis/openfoam_worker.py")
script = linux_path("analysis/openfoam_environment.sh")
subprocess.run(prefix + ["bash", "--noprofile", "--norc", script, worker, linux_path(request_file)],
               stdout=sys.stderr, stderr=sys.stderr, check=True, timeout=180)
response = json.loads((output/"foam-result.json").read_text())
for value in response["outputs"].values():
    if "path" in value:
        value["path"] = str(output / Path(value["path"]).name)
json.dump(response, sys.stdout, allow_nan=False)
