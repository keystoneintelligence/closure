"""Independent solid-volume checks on exported B-reps at solved sample poses.

This audit does not reconstruct the cam or infer noninterference from its height
functions. It reloads the actual CAD artifact and applies the motion artifact.
"""
import contextlib
import io
import itertools
import json
import sys
import zipfile
from pathlib import Path
from protocol import read, write, quantity as q, scalar as s, artifact

request, v, out = read()
settings = request["settings"]
checked_clicks = int(settings["checked_clicks"])
tolerance = settings["intersection_tolerance_mm3"]
with contextlib.redirect_stdout(sys.stderr):
    import cadquery as cq

    with zipfile.ZipFile(v["parts"]) as archive:
        parts = {Path(name).stem: cq.Shape.importBrep(io.BytesIO(archive.read(name)))
                 for name in archive.namelist() if name.endswith(".brep")}
    motion = json.loads(Path(v["motion"]).read_text())
    points = motion["samples"][:motion["ends"][checked_clicks-1]["sample_end"]+1]
    selected = [points[0]]
    for index, point in enumerate(points[1:], 1):
        previous = selected[-1]
        if (abs(point["rotor_deg"]-previous["rotor_deg"]) >= settings["angular_sample_deg"] or
            abs(point["rotor_mm"]-previous["rotor_mm"]) >= settings["axial_sample_mm"] or
            abs(point["button_mm"]-previous["button_mm"]) >= settings["axial_sample_mm"] or
            point["phase"] != points[index-1]["phase"] or
            point["sleeve_contact"] != points[index-1]["sleeve_contact"] or
            point["click"] != points[index-1]["click"]):
            selected.append(point)
    if selected[-1] is not points[-1]:
        selected.append(points[-1])
    moving = {"button", "rotor", "refill", "spring_seat"}
    rigid = {k: shape for k, shape in parts.items() if k != "spring"}
    all_pairs = list(itertools.combinations(sorted(rigid), 2))
    dynamic_pairs = [(a,b) for a,b in all_pairs if a in moving or b in moving]
    records, overlaps, maximum = [], [], 0.0

    def overlap(a, b):
        left, right = a.BoundingBox(), b.BoundingBox()
        if any(getattr(left, axis+"max") <= getattr(right, axis+"min")+settings["bounding_box_epsilon_mm"] or
               getattr(right, axis+"max") <= getattr(left, axis+"min")+settings["bounding_box_epsilon_mm"] for axis in "xyz"):
            return 0.0
        return max(0.0, a.intersect(b).Volume())

    for index, point in enumerate(selected):
        posed = dict(rigid)
        for name in ("refill", "spring_seat", "rotor"):
            posed[name] = posed[name].translate((0,0,-point["rotor_mm"]))
        posed["rotor"] = posed["rotor"].rotate((0,0,0),(0,0,1),point["rotor_deg"])
        posed["button"] = posed["button"].translate((0,0,-point["button_mm"]))
        pairs = all_pairs if index == 0 else dynamic_pairs
        for a,b in pairs:
            volume = overlap(posed[a], posed[b])
            maximum = max(maximum, volume)
            if volume > tolerance:
                overlaps.append({"sample": index, "parts": [a,b], "volume_mm3": volume})
        records.append(point)
    solid_valid = all(shape.isValid() and len(shape.Solids())==1 and shape.Volume()>0 for shape in parts.values())
    audit = {"schema": "closure-contact-audit/0.1", "sample_count": len(selected),
             "parts": sorted(parts), "all_connected_valid": solid_valid,
             "maximum_intersection_mm3": maximum, "tolerance_mm3": tolerance,
             "samples": records, "overlaps": overlaps,
             "scope": f"First {checked_clicks} nominal rigid-body cycles, including initial and settled backlash. Static pairs checked at the first pose. Deformable spring, manufacturing tolerance, elastic contact and continuous-between-sample guarantees excluded."}
    (out/"contact_audit.json").write_text(json.dumps(audit, indent=2))
write(request, {"valid":s(solid_valid and not overlaps), "max_intersection":q(maximum,"mm^3"),
                "sample_count":s(len(selected)), "audit":artifact(out/"contact_audit.json")})
