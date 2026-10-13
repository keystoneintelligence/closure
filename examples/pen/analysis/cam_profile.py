"""Shared dimensions for the pen's rotary face cams, in mm and degrees.

The motion solution follows local minima of spring compression under unilateral
button/sleeve constraints. No alternating state or rotation is assigned by click.
"""
import math


class CamProfile:
    def __init__(self, values):
        self.v = values
        self.count = int(values["lug_count"])
        self.pitch = 360 / (2 * self.count)
        self.height = values["tooth_height"]
        self.phase = values["phase_offset"]
        self.travel = values["travel"]
        self.stroke = values["full_stroke"]
        self.lip = self.stroke - self.height - values["release_gap"]
        self.rotor_radius = values["rotor_diameter"] / 2
        self.inner = self.rotor_radius + values["rotor_clearance"] / 2
        self.outer = self.rotor_radius + values["lug_depth"]
        self.contact_radius = (self.inner + self.outer) / 2
        self.lug_angle = math.degrees(values["lug_width"] / self.contact_radius)
        self.slot_angle = math.degrees(values["slot_width"] / self.contact_radius)
        self.initial_angle = -(self.slot_angle - self.lug_angle) / 2
        self.reference = self.separation(self.initial_angle)
        self.crown_slope = 2 * self.height / (math.radians(self.pitch) * values["cam_radius"])
        self.return_slopes = [(self.lip - end) / (self.contact_radius * math.radians(self.pitch - self.slot_angle))
                              for end in (self.travel, 0)]
        if not (0 < self.lug_angle < self.slot_angle < self.pitch and self.lip > self.travel
                and self.outer < values["sleeve_diameter"] / 2):
            raise ValueError("Cam dimensions cannot provide separate guide slots and return ramps")
        if not (0 < self.phase + self.initial_angle < self.pitch / 2):
            raise ValueError("Crown phase must initiate forward rotation throughout guide clearance")

    def crown(self, angle):
        """Top of each symmetric triangular tooth above its root plane."""
        offset = (angle + self.pitch / 2) % self.pitch - self.pitch / 2
        return self.height * (1 - abs(offset) / (self.pitch / 2))

    def separation(self, angle):
        """Maximum sum of opposing crown heights over one complete face ring."""
        offset = (angle + self.phase) % self.pitch
        return self.height * (1 + abs(offset - self.pitch / 2) / (self.pitch / 2))

    def wall(self, angle):
        """Minimum downward travel beneath the sleeve roof at one angle."""
        index = math.floor(angle / self.pitch)
        offset = angle - index * self.pitch
        if offset <= self.slot_angle / 2:
            return self.travel * (index % 2)
        following = self.travel * ((index + 1) % 2)
        if offset >= self.pitch - self.slot_angle / 2:
            return following
        fraction = (offset - self.slot_angle / 2) / (self.pitch - self.slot_angle)
        return self.lip + (following - self.lip) * fraction

    def sleeve(self, angle):
        """Finite-width follower envelope, including vertical slot shoulders."""
        low, high = angle - self.lug_angle / 2, angle + self.lug_angle / 2
        candidates = [low, high]
        for index in range(math.floor(low / self.pitch) - 1, math.ceil(high / self.pitch) + 1):
            for corner in (index * self.pitch + self.slot_angle / 2,
                           (index + 1) * self.pitch - self.slot_angle / 2):
                if low < corner < high:
                    candidates.extend((corner - 1e-8, corner + 1e-8))
        return max(self.wall(point) for point in candidates)

    def compression(self, angle, hand):
        return max(0, self.sleeve(angle), hand + self.separation(angle) - self.reference)

    def solve(self, clicks=2, axial_step=0.025, angular_step=0.05):
        angle = self.initial_angle
        button = 0.0
        samples, ends = [], []
        for click in range(clicks):
            start = len(samples)
            for phase, begin, end in (("press", button, self.stroke), ("release", self.stroke, 0)):
                steps = max(1, math.ceil(abs(end - begin) / axial_step))
                for step in range(steps + 1):
                    hand = begin + (end - begin) * step / steps
                    for iteration in range(2000):
                        q = self.compression(angle, hand)
                        candidates = [(self.compression(angle + direction * angular_step, hand), angle + direction * angular_step)
                                      for direction in (-1, 1)]
                        candidate_q, candidate_angle = min(candidates)
                        if candidate_q >= q - 1e-9:
                            break
                        angle = candidate_angle
                    else:
                        raise ValueError("Quasi-static contact search did not settle")
                    q = self.compression(angle, hand)
                    button = max(hand, q - self.separation(angle) + self.reference)
                    samples.append({"click": click + 1, "phase": phase, "hand_mm": hand,
                                    "button_mm": button, "rotor_mm": q,
                                    "rotor_deg": angle - self.initial_angle,
                                    "sleeve_contact": abs(q - self.sleeve(angle)) < 1e-6})
            q = samples[-1]["rotor_mm"]
            state = "retracted" if abs(q) < 1e-5 else "extended" if abs(q - self.travel) < 1e-5 else "unsettled"
            ends.append({"click": click + 1, "state": state, "rotor_mm": q,
                         "button_mm": button, "rotor_deg": angle - self.initial_angle,
                         "sample_start": start, "sample_end": len(samples) - 1})
        return {"schema": "closure-cam-motion/0.1", "samples": samples, "ends": ends,
                "initial_angle_deg": self.initial_angle, "reference_separation_mm": self.reference,
                "max_rotor_stroke_mm": max(sample["rotor_mm"] for sample in samples),
                "crown_angle_deg": math.degrees(math.atan(self.crown_slope)),
                "minimum_return_angle_deg": math.degrees(math.atan(min(self.return_slopes))),
                "minimum_return_slope": min(self.return_slopes),
                "maximum_reverse_rotation_deg": max(0, max((a["rotor_deg"] - b["rotor_deg"] for a, b in zip(samples, samples[1:])), default=0)),
                "scope": "Rigid, quasi-static contact envelope; massless guided button; friction feasibility checked separately. No impact, wear, or physical lifetime validation."}
