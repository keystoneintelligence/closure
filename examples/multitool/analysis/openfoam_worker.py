"""Run actual blockMesh/checkMesh/icoFoam and inspect the resulting velocity field."""
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

request = json.loads(Path(sys.argv[1]).read_text())
v = {k: item["value"] for k, item in request["inputs"].items()}
output = Path(request["output_dir"])
case = output / "cavity"
shutil.copytree(request["case_source"], case)
(case / "closureParameters").write_text(
    f'L {v["length"]:.12g};\nH {v["height"]:.12g};\nD {v["depth"]:.12g};\n'
    f'lidVelocity ({v["lid_speed"]:.12g} 0 0);\nkinematicViscosity {v["viscosity"]:.12g};\n'
    f'endTimeValue {v["end_time"]:.12g};\ndeltaTValue {v["time_step"]:.12g};\n')
tools = {}
logs = {}
for name in ("blockMesh", "checkMesh", "icoFoam"):
    executable = shutil.which(name)
    if not executable:
        raise RuntimeError(f"OpenFOAM executable missing: {name}")
    tools[name] = {"path": executable, "sha256": hashlib.sha256(Path(executable).read_bytes()).hexdigest()}
    log = output / (name + ".log")
    with log.open("w") as stream:
        subprocess.run([executable, "-case", str(case)], stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=120)
    logs[name] = log.read_text()
if "Mesh OK." not in logs["checkMesh"]:
    raise RuntimeError("OpenFOAM mesh checks did not pass")
numeric = r"[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[Ee][-+]?\d+)?"
times = re.findall(r"^Time = ("+numeric+r")$", logs["icoFoam"], re.M)
if not times or abs(float(times[-1])-v["end_time"]) > max(v["time_step"]*.01, 1e-9):
    raise RuntimeError("Solver did not reach the requested final time")
courant = [float(n) for n in re.findall(r"Courant Number mean: .*? max: ("+numeric+")", logs["icoFoam"])]
residuals = [float(n) for n in re.findall(r"Final residual = ("+numeric+")", logs["icoFoam"])]
continuity = [float(n) for n in re.findall(r"cumulative = ("+numeric+")", logs["icoFoam"])]
if not courant or not residuals or not continuity:
    raise RuntimeError("Solver diagnostics are missing")
field = (case / times[-1] / "U").read_text()
match = re.search(r"internalField\s+nonuniform\s+List<vector>\s+(\d+)\s*\((.*?)\)\s*;", field, re.S)
if not match:
    raise RuntimeError("Expected a nonuniform final velocity field")
vectors = [[float(n) for n in re.findall(numeric, text)] for text in re.findall(r"\(([^()]+)\)", match[2])]
if len(vectors) != int(match[1]) or any(len(vector) != 3 or not all(map(math.isfinite, vector)) for vector in vectors):
    raise RuntimeError("Malformed or nonfinite velocity field")
maximum = max(math.sqrt(sum(component**2 for component in vector)) for vector in vectors)
diagnostics = {"tools": tools, "package_version": subprocess.check_output(["dpkg-query", "-W", "-f=${Version}", "openfoam"], text=True),
               "final_time_s": float(times[-1]), "cells": len(vectors), "max_courant": max(courant),
               "max_linear_final_residual": max(residuals), "cumulative_continuity_error": continuity[-1],
               "maximum_internal_velocity_m_s": maximum, "negative_x_cells": sum(u[0]<0 for u in vectors),
               "scope": "Transient laminar lid-driven cavity; time completion and linear solves checked. No claim of steady-state or mesh convergence."}
(output / "flow.json").write_text(json.dumps(diagnostics, indent=2))
(case / "cavity.foam").touch()
with zipfile.ZipFile(output / "cavity-case.zip", "w", zipfile.ZIP_DEFLATED) as archive:
    for path in case.rglob("*"):
        if path.is_file():
            archive.write(path, path.relative_to(case))
    for name in logs:
        archive.write(output/(name+".log"), "logs/"+name+".log")
q = lambda value, unit: {"value": value, "unit": unit}
s = lambda value: {"value": value}
converged = all(map(math.isfinite, [*courant, *residuals, *continuity])) and max(residuals) < 1e-5
response = {"protocol": "closure-run/0.1", "invocation_id": request["invocation_id"], "converged": converged,
            "residuals": {"max_linear_final": max(residuals), "continuity": continuity[-1]}, "outputs": {
                "mesh_valid": s(True), "cells": s(len(vectors)), "final_time": q(float(times[-1]), "s"),
                "max_courant": s(max(courant)), "continuity_error": s(abs(continuity[-1])),
                "max_velocity": q(maximum, "m/s"), "recirculating_cells": s(sum(u[0]<0 for u in vectors)),
                "diagnostics": {"path": "flow.json", "media_type": "application/json"},
                "case": {"path": "cavity-case.zip", "media_type": "application/zip"}}}
(output/"foam-result.json").write_text(json.dumps(response, allow_nan=False))
