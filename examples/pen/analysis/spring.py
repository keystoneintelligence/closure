"""Round-wire compression spring with Wahl correction and tolerance envelopes."""
import json
import math
from protocol import read, write, quantity as q, scalar as s, artifact

request, v, out = read()
# Dimensionless coefficient in the Wahl curvature correction, not a design input.
WAHL_CURVATURE_TERM = 0.615
d, D, n = v["wire"], v["mean_diameter"], v["active_coils"]
assert d > 0 and D > 4*d and n > 2
index = D / d
wahl = (4 * index - 1)/(4 * index - 4) + WAHL_CURVATURE_TERM/index
rate = v["shear_modulus"] * d**4 / (8 * D**3 * n)
preload = v["free_length"] - v["installed_length"]
compression = preload + v["stroke"]
assert preload > 0 and compression > preload
force_min, force_max = rate * preload, rate * compression
stress_min = wahl * 8 * force_min * D / (math.pi * d**3)
stress_max = wahl * 8 * force_max * D / (math.pi * d**3)
# Rate tolerance covers coil/process variation; geometric tolerances protect fit/stress.
force_worst = rate * (1 + v["rate_tolerance"]) * (compression + 2*v["length_tolerance"])
d_min, D_max = d-v["wire_tolerance"], D+v["diameter_tolerance"]
index_worst = D_max/d_min
wahl_worst = (4*index_worst-1)/(4*index_worst-4)+WAHL_CURVATURE_TERM/index_worst
stress_worst = wahl_worst*8*force_worst*D_max/(math.pi*d_min**3)
total_coils = n + v["inactive_coils"]
solid_max = v["solid_height_factor"] * total_coils * (d + v["wire_tolerance"])
solid_clearance = v["installed_length"] - v["stroke"] - 2*v["length_tolerance"] - solid_max
fatigue_factor = 1 / (((stress_max-stress_min)/2)/v["alternating_allowable"] + ((stress_max+stress_min)/2)/v["mean_allowable"])
wire_length = math.hypot(math.pi*D*total_coils, v["free_length"]-d)
volume = math.pi*d*d/4*wire_length
intervals = int(request["settings"]["curve_intervals"])
assert intervals > 0
curve = [{"displacement_mm": x/intervals*v["stroke"], "force_N": rate*(preload+x/intervals*v["stroke"])} for x in range(intervals+1)]
(out/"spring_curve.json").write_text(json.dumps({"curve":curve,"model":"linear helical spring; guided, elastic; fatigue is a screening calculation"},indent=2))
write(request, {"rate":q(rate,"N/mm"), "preload_force":q(force_min,"N"), "peak_force":q(force_max,"N"),
                "worst_force":q(force_worst,"N"), "shear_stress":q(stress_worst,"MPa"), "safety_factor":s(v["shear_allowable"]/stress_worst),
                "fatigue_factor":s(fatigue_factor), "solid_clearance":q(solid_clearance,"mm"), "solid_height":q(solid_max,"mm"),
                "outer_diameter":q(D+d+v["diameter_tolerance"]+v["wire_tolerance"],"mm"),
                "inner_diameter":q(D-d-v["diameter_tolerance"]-v["wire_tolerance"],"mm"),
                "volume":q(volume,"mm^3"), "curve":artifact(out/"spring_curve.json")})
