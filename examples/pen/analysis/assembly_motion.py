"""Generic assembly keyframes derived from the solved cam motion."""


def animation_metadata(motion, installed, spring_bottom):
    def transforms(sample, rotation_offset=0):
        q = sample["rotor_mm"]
        return [
            {"parts": ["refill", "spring_seat", "rotor"], "translation_mm": [0, 0, -q]},
            {"parts": ["rotor"], "rotation_deg": [0, 0, sample["rotor_deg"] - rotation_offset]},
            {"parts": ["button"], "translation_mm": [0, 0, -sample["button_mm"]]},
            {"parts": ["spring"], "scale_axis": "z", "scale": (installed-q)/installed,
             "pivot_mm": [0, 0, spring_bottom]}]

    samples, ends = motion["samples"], motion["ends"]
    period = motion["rotational_period_deg"]
    transitions = []
    for click, begin, end, offset in ((0, "retracted", "extended", 0),
                                     (1, "extended", "returned", 0),
                                     (2, "returned", "extended", period)):
        lo, hi = ends[click]["sample_start"], ends[click]["sample_end"]
        frames = sorted(set(range(lo, hi+1, 3)) | {lo, hi})
        transitions.append({"from": begin, "to": end, "duration_ms": 1200,
            "keyframes": [{"t": (index-lo)/(hi-lo), "motions": transforms(samples[index], offset)}
                          for index in frames]})
    # Identical followers give the period exported by the motion solver. Preserve
    # the solved return backlash rather than snapping the rotor to its first pose.
    return {"states": [{"id": "retracted", "label": "Retracted"},
                       {"id": "extended", "label": "Extended"},
                       {"id": "returned", "label": "Retracted"}],
            "motions": [dict(item, state=state) for state, sample, offset in
                        (("extended", samples[ends[0]["sample_end"]], 0),
                         ("returned", samples[ends[1]["sample_end"]], period))
                        for item in transforms(sample, offset)],
            "actuation": {"label": "Press button", "transitions": transitions}}
