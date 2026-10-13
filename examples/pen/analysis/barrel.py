"""Elastic, simply supported three-point bending of the barrel section."""
import math
from protocol import read, write, quantity as q, scalar as s

request, v, out = read()
outer, inner = v["diameter"], v["diameter"] - 2 * v["wall"]
assert outer > inner > 0 and 0 < v["span"] <= v["length"]
area = math.pi / 4 * (outer**2 - inner**2)
inertia = math.pi / 64 * (outer**4 - inner**4)
moment = v["bending_load"] * v["span"] / 4
stress = moment * (outer / 2) / inertia
axial = v["axial_load"] / area
# Sum surface axial and bending stresses conservatively for this simple load case.
combined = stress + axial
deflection = v["bending_load"] * v["span"]**3 / (48 * v["modulus"] * inertia)
write(request, {"inner_diameter": q(inner, "mm"), "area": q(area, "mm^2"), "inertia": q(inertia, "mm^4"),
                "stress": q(combined, "MPa"), "deflection": q(deflection, "mm"),
                "safety_factor": s(v["yield_strength"] / combined), "volume": q(area * v["length"], "mm^3")})
