"""Native B-rep geometry built from the shared cam height functions."""
import math
import cadquery as cq
from cam_profile import CamProfile


def cylinder(radius, height, z=0):
    return cq.Solid.makeCylinder(radius, height, cq.Vector(0, 0, z))


def tube(outer, inner, height, z=0):
    return cylinder(outer, height, z).cut(cylinder(inner, height, z))


def sloping_sector(inner, outer, begin, end, bottom, roof, *, increment):
    """Ruled radial sections; the angular resolution is recorded with the CAD."""
    wires = []
    steps = max(1, math.ceil(abs(end - begin) / increment))
    for index in range(steps + 1):
        angle = begin + (end - begin) * index / steps
        radians = math.radians(angle)
        top = roof(angle)
        if top <= bottom:
            raise ValueError("Cam sector must have positive height")
        points = [cq.Vector(r * math.cos(radians), r * math.sin(radians), z)
                  for r, z in ((inner, bottom), (outer, bottom), (outer, top), (inner, top))]
        wires.append(cq.Wire.makePolygon(points, close=True))
    return cq.Solid.makeLoft(wires, ruled=True)


def crown(profile, z, settings):
    inner, outer = profile.v["cam_radius"] - profile.v["crown_width"]/2, profile.v["cam_radius"] + profile.v["crown_width"]/2
    pieces = []
    for index in range(2 * profile.count):
        center = index * profile.pitch
        for begin, end in ((center - profile.pitch / 2, center), (center, center + profile.pitch / 2)):
            pieces.append(sloping_sector(inner, outer, begin, end, z - settings["crown_root_overlap_mm"],
                                         lambda angle: z + profile.crown(angle), increment=settings["angular_section_deg"]))
    return pieces


def make_parts(values, rear, end, settings):
    p = CamProfile(values)
    overlap = settings["boolean_overlap_mm"]
    relief = settings["surface_relief_mm"]
    def sector(*args):
        return sloping_sector(*args, increment=settings["angular_section_deg"])
    head_base = rear + values["rotor_stem_length"]
    head_top = head_base + values["rotor_head_height"]
    lug_base = head_base + values["lug_offset"]
    lug_top = lug_base + values["lug_height"]
    sleeve_bottom, sleeve_top = lug_top - p.lip, end - values["cap_spigot_length"]
    rotor = cylinder(values["rotor_stem"] / 2, values["rotor_stem_length"], rear)
    rotor = rotor.fuse(cylinder(p.rotor_radius, values["rotor_head_height"], head_base))
    for index in range(p.count):
        angle = index * p.pitch * 2
        lug = sector(p.rotor_radius - overlap, p.outer, angle - p.lug_angle / 2,
                             angle + p.lug_angle / 2, lug_base, lambda phi: lug_top)
        rotor = rotor.fuse(lug)
    for tooth in crown(p, head_top, settings):
        rotor = rotor.fuse(tooth)
    rotor = rotor.rotate((0, 0, 0), (0, 0, 1), p.initial_angle)

    sleeve = tube(values["sleeve_diameter"] / 2, p.inner, sleeve_top - sleeve_bottom, sleeve_bottom)
    cuts = []
    for index in range(2 * p.count):
        center = index * p.pitch
        roof = lug_top - p.travel * (index % 2)
        cuts.append(sector(p.inner - overlap, p.outer + values["slot_radial_clearance"], center - p.slot_angle / 2,
                                  center + p.slot_angle / 2, sleeve_bottom - overlap, lambda phi: roof + relief))
        begin, finish = center + p.slot_angle / 2, center + p.pitch - p.slot_angle / 2
        # The lip's jump is a real vertical shoulder; it is not lofted across the slot.
        cuts.append(sector(p.inner - overlap, p.outer + values["slot_radial_clearance"], begin, finish, sleeve_bottom - overlap,
                                  lambda phi, a=begin, b=finish, i=index: lug_top - (p.lip + (p.travel * ((i+1) % 2) - p.lip) * (phi-a)/(b-a)) + relief))
    sleeve = sleeve.cut(cq.Compound.makeCompound(cuts))
    # A lower retaining collar remains outside the follower's complete stroke.
    sleeve = sleeve.fuse(tube(values["barrel_inner"] / 2 - values["sleeve_housing_clearance"], p.outer + values["follower_running_clearance"], values["collar_thickness"], sleeve_bottom - values["collar_thickness"]))

    button_base = head_top + p.reference + relief
    button_top = end + values["cap_length"] + values["button_projection"]
    button = cylinder(values["button_shaft"] / 2, button_top - button_base, button_base)
    button = button.fuse(cylinder(p.rotor_radius - values["button_rotor_clearance"], values["button_crown_base_thickness"], button_base))
    button = button.fuse(cylinder(values["button_diameter"] / 2, values["button_projection"], end + values["cap_length"]))
    for tooth in crown(p, 0, settings):
        button = button.fuse(tooth.mirror("XY").rotate((0,0,0), (0,0,1), -p.phase).translate((0,0,button_base)))
    guide_base = lug_top + p.stroke + values["plunger_guide_gap"]
    for index in range(p.count):
        angle = index * 2 * p.pitch + p.pitch / 2
        guide_inner = values["button_shaft"] / 2 - overlap
        guide = cq.Workplane("XY").box(p.outer - guide_inner, values["lug_width"], sleeve_top - guide_base)
        guide = guide.translate(((p.outer + guide_inner) / 2, 0, (guide_base+sleeve_top)/2)).val()
        button = button.fuse(guide.rotate((0,0,0), (0,0,1), angle))
        clearance = cq.Workplane("XY").box(values["plunger_slot_depth"], values["slot_width"], sleeve_top-lug_top)
        clearance = clearance.translate((p.rotor_radius + values["plunger_slot_offset"], 0, (sleeve_top+lug_top)/2+settings["plunger_slot_overrun_mm"])).val()
        sleeve = sleeve.cut(clearance.rotate((0,0,0), (0,0,1), angle))
        key = cq.Workplane("XY").box(values["key_depth"], values["key_width"], values["key_length"])
        key = key.translate((p.inner+values["key_depth"]/2, 0, sleeve_top+values["key_length"]/2-values["key_engagement"])).val()
        sleeve = sleeve.fuse(key.rotate((0,0,0), (0,0,1), index*2*p.pitch))
    return {"rotor": rotor.clean(), "cam_sleeve": sleeve.clean(), "button": button.clean()}, {
        "lug_top_mm": lug_top, "sleeve_bottom_mm": sleeve_bottom, "sleeve_top_mm": sleeve_top,
        "button_base_mm": button_base, "button_top_mm": button_top, "initial_rotor_angle_deg": p.initial_angle,
        "angular_section_deg": settings["angular_section_deg"], "numerical_surface_relief_mm": relief}
