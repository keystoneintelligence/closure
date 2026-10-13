"""Compute the contact-constrained cycle before the spring force calculation."""
import json
from cam_profile import CamProfile
from protocol import read, write, quantity as q, scalar as s, artifact

request, v, out = read()
profile = CamProfile(v)
settings = request["settings"]
axial, angular = settings["axial_step_mm"], settings["angular_step_deg"]
refinement = settings["refinement_factor"]
assert axial > 0 and angular > 0 and refinement > 1
motion = profile.solve(clicks=int(settings["clicks"]), axial_step=axial, angular_step=angular)
motion["rotational_period_deg"] = 360 / profile.count
ends = motion["ends"]
valid = all(end["state"] == ("extended" if i % 2 == 0 else "retracted")
            for i, end in enumerate(ends))
# A second resolution is a convergence check, not a second physical model.
refined = profile.solve(clicks=int(settings["refined_clicks"]), axial_step=axial/refinement, angular_step=angular/refinement)
converged = all(a["state"] == b["state"] for a, b in zip(ends, refined["ends"]))
stroke_difference = abs(motion["max_rotor_stroke_mm"] - refined["max_rotor_stroke_mm"])
motion["convergence"] = {"refined_axial_step_mm": axial/refinement, "refined_angular_step_deg": angular/refinement,
                         "same_end_states": converged, "max_stroke_difference_mm": stroke_difference}
motion["resolution"] = {"axial_step_mm": axial, "angular_step_deg": angular}
motion["cycle_valid"] = valid and converged and stroke_difference < settings["stroke_convergence_mm"]
(out / "cam_motion.json").write_text(json.dumps(motion, indent=2))
write(request, {"cycle": artifact(out / "cam_motion.json"), "cycle_valid": s(motion["cycle_valid"]),
    "max_rotor_stroke": q(motion["max_rotor_stroke_mm"], "mm"),
    "release_clearance": q(motion["max_rotor_stroke_mm"] - profile.lip - 2*v["machining_tolerance"], "mm"),
    "minimum_return_slope": s(min(profile.return_slopes)),
    "minimum_crown_slope": s(2*profile.height / (__import__('math').radians(profile.pitch)*(v["cam_radius"]+v["crown_width"]/2))),
    "contact_radius": q(profile.contact_radius, "mm")})
