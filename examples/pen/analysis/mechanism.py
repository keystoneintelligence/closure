"""Force and friction feasibility screen of the solved cam contact cycle."""
import json
from pathlib import Path
from protocol import read, write, quantity as q, scalar as s, artifact

request, v, out = read()
mu = v["friction_coefficient"]
minimum_slope = min(v["minimum_return_slope"], v["minimum_crown_slope"])
# Conservative work/loss screen; guide drag is a declared lumped assumption.
push_force = v["spring_peak"]*(1+mu/minimum_slope) + v["sliding_friction"]
# Coulomb sliding on the shallowest return ramp, evaluated at preload.
return_torque = v["spring_preload"]*v["contact_radius"]*(v["minimum_return_slope"]-mu)/(1+mu*v["minimum_return_slope"])
bearing = push_force/(v["lug_count"]*v["lug_width"]*v["lug_depth"])
clearance = v["slot_width"]-v["lug_width"]-2*v["machining_tolerance"]
release_clearance = v["release_clearance"]
spring_guide_clearance = v["spring_inner"]-v["guide_diameter"]-2*v["machining_tolerance"]
radial_clearance = v["barrel_inner"]-v["sleeve_diameter"]-2*v["machining_tolerance"]
motion = json.loads(Path(v["motion"]).read_text())
valid = v["motion_valid"] and minimum_slope>mu and release_clearance>0 and return_torque>0
(out/"mechanism_cycle.json").write_text(json.dumps({"schema":"closure-motion-screen/0.1", "ends":motion["ends"],
    "cycle_valid":valid, "minimum_slope":minimum_slope,
    "assumptions":["Friction coefficient bounded by the declared input", "Rigid quasi-static contact envelopes and lumped guide drag", "No impact, creep, or wear model"]},indent=2))
write(request, {"push_force":q(push_force,"N"), "return_torque":q(return_torque,"N*mm"),
                "bearing_stress":q(bearing,"MPa"), "bearing_factor":s(v["bearing_allowable"]/bearing),
                "slot_clearance":q(clearance,"mm"), "release_clearance":q(release_clearance,"mm"),
                "guide_clearance":q(spring_guide_clearance,"mm"), "sleeve_clearance":q(radial_clearance,"mm"),
                "tip_extension":q(v["travel"]-v["retracted_gap"],"mm"),
                "tip_retraction":q(v["retracted_gap"]-v["axial_stack_tolerance"],"mm"),
                "cycle_valid":s(valid), "cycle":artifact(out/"mechanism_cycle.json")})
