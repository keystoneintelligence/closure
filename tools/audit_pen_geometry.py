"""Independent B-rep overlap audit of the pen's named component solids."""
import contextlib
import io
import json
import sys
import tempfile
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
project = ROOT / "examples/pen"
report = json.loads((project / ".closure/report.json").read_text())
record = next(a["record"] for a in report["analyses"] if a["id"] == "manufacturing.cad")
source = (project / "analysis/cad.py").read_text().split('    assembly=cq.Assembly')[0]
sys.path.insert(0, str(project / "analysis"))
with tempfile.TemporaryDirectory() as directory:
    request = {"protocol": "closure-run/0.1", "invocation_id": "geometry-audit", "inputs": record["inputs"], "output_dir": directory}
    sys.stdin = io.StringIO(json.dumps(request))
    context = {}
    exec(compile(source, str(project / "analysis/cad.py"), "exec"), context)
    parts = context["parts"]
    results = {"record": record["id"], "sources": record["sources"],
               "solid_counts": {p["id"]: len(p["shape"].Solids()) for p in parts}, "states": [],
               "scope": "Rigid component interference in the two nominal stable positions; deformable spring and transition contact excluded."}
    for state, distance, angle in (("retracted", 0, 0), ("extended", -3, 60)):
        shapes = {}
        for part in parts:
            shape = part["shape"]
            if part["id"] in ("rotor", "spring_seat", "refill"):
                shape = shape.translate((0, 0, distance))
            if part["id"] == "rotor":
                shape = shape.rotate((0, 0, 0), (0, 0, 1), angle)
            # The deformable spring is audited separately; it is not a rigid translation.
            if part["id"] != "spring":
                shapes[part["id"]] = shape
        overlaps = []
        for a, b in combinations(shapes, 2):
            volume = shapes[a].intersect(shapes[b]).Volume()
            if volume > .001:
                overlaps.append({"parts": [a, b], "volume_mm3": volume})
        results["states"].append({"state": state, "overlaps": overlaps})
    results["passed"] = all(n == 1 for n in results["solid_counts"].values()) and not any(s["overlaps"] for s in results["states"])
    destination = ROOT / "docs/verification/pen-geometry-audit.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results))
    raise SystemExit(0 if results["passed"] else 1)
