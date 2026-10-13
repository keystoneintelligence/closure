"""Development probe of the proposed contact model before changing CAD."""
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "examples/pen/analysis"))
from cam_profile import CamProfile

report = json.loads((root / "examples/pen/.closure/report.json").read_text())
values = {key.split(".")[-1]: value["value"] for key, value in report["values"].items()
          if key.startswith("mechanism.") and key.count(".") == 1 and "value" in value}
values.update(full_stroke=6, phase_offset=5, release_gap=0.6)
profile = CamProfile(values)
motion = profile.solve(clicks=12)
print(json.dumps({k: v for k, v in motion.items() if k != "samples"}, indent=2))
destination = root / ".closure/pen-cam-probe.json"
destination.parent.mkdir(exist_ok=True)
destination.write_text(json.dumps(motion), encoding="utf-8")
