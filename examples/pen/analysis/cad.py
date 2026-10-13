"""Parametric solid assembly. Design dimensions enter through team contracts; meshing settings are explicit."""
import contextlib
import json
import math
import sys
from protocol import read, write, quantity as q, scalar as s, artifact

request, v, out = read()
with contextlib.redirect_stdout(sys.stderr):
    import cadquery as cq
    import numpy as np
    import trimesh

    def tube(outer, inner, height, z=0):
        return cq.Workplane("XY").circle(outer).circle(inner).extrude(height).translate((0,0,z)).val()

    def cylinder(radius, height, z=0):
        return cq.Solid.makeCylinder(radius,height,cq.Vector(0,0,z))

    settings = request["settings"]
    extra = settings["cutter_extra_mm"]
    diameter, inner, length = v["barrel_diameter"], v["barrel_inner"], v["barrel_length"]
    nose_h=v["nose_length"]
    end=nose_h+length
    tip=v["retracted_gap"]
    shoulder=tip+v["refill_shoulder"]
    rear=tip+v["refill_length"]
    seat_top=shoulder-v["seat_thickness"]
    spring_bottom=seat_top-v["spring_installed"]
    assert spring_bottom>0 and spring_bottom<nose_h
    parts=[]
    def add(name,shape,team,material,color,process,explode, moving=False):
        if not shape.isValid() or shape.Volume()<=0 or len(shape.Solids()) != 1:
            raise ValueError(f"Invalid solid: {name}")
        parts.append({"id":name,"shape":shape,"team":team,"material":material,"color":color,"process":process,"explode":explode,"moving":moving})

    from cam_solid import make_parts
    from cam_profile import CamProfile
    cam_parts, cam_datums = make_parts(v, rear, end, settings)
    profile = CamProfile(v)
    barrel=tube(diameter/2,inner/2,length,nose_h)
    # Integral shoulder captures the sleeve collar while the followers pass below it.
    barrel=barrel.fuse(tube(inner/2+settings["housing_fuse_overlap_mm"],profile.outer+v["follower_running_clearance"],v["capture_shoulder_thickness"],cam_datums["sleeve_bottom_mm"]-v["collar_thickness"]-v["capture_shoulder_thickness"]))
    add("barrel",barrel,"barrel","aluminum",[34,61,80,255],"Turn and bore 6061 tube; hard anodize",[0,0,0])

    nose=cq.Solid.makeCone(v["nose_tip_diameter"]/2,diameter/2,nose_h)
    nose=nose.fuse(cylinder(inner/2-v["joint_radial_clearance"],v["thread_engagement"],nose_h))
    nose=nose.cut(cylinder(v["tip_bore"]/2,nose_h+v["thread_engagement"]+2*extra,-extra))
    nose=nose.cut(cylinder(v["spring_cavity"]/2,nose_h+v["thread_engagement"]-spring_bottom+2*extra,spring_bottom))
    add("nose",nose,"barrel","aluminum",[202,211,217,255],"Turn; mating thread envelope only; thread dimensions require detail design",[0,0,-24])

    cap=cylinder(diameter/2,v["cap_length"],end).fuse(cylinder(inner/2-v["joint_radial_clearance"],v["cap_spigot_length"],end-v["cap_spigot_length"]))
    cap=cap.cut(cylinder(v["button_shaft"]/2+v["button_radial_clearance"],v["cap_length"]+v["cap_spigot_length"]+2*extra,end-v["cap_spigot_length"]-extra))
    cap=cap.cut(cylinder(v["button_diameter"]/2+v["button_radial_clearance"],v["full_stroke"]+extra,end+v["cap_length"]-v["full_stroke"]))
    cap=cap.cut(cylinder(v["sleeve_diameter"]/2-v["cap_register_lip"],v["cap_spigot_length"]+2*settings["register_cut_overrun_mm"],end-v["cap_spigot_length"]-settings["register_cut_overrun_mm"]))
    for index in range(profile.count):
        pocket_height=v["key_length"]-v["key_engagement"]-v["cap_spigot_length"]+v["key_clearance"]
        assert pocket_height > 0
        pocket=cq.Workplane("XY").box(v["key_depth"]+v["key_clearance"],v["key_width"]+v["key_clearance"],pocket_height).translate((profile.inner+v["key_depth"]/2,0,end+pocket_height/2)).val()
        cap=cap.cut(pocket.rotate((0,0,0),(0,0,1),index*profile.pitch*2))
    add("cap",cap,"barrel","aluminum",[196,205,212,255],"Turn with counterbore; threaded retaining cap (cosmetic envelope)",[0,0,24])

    stem_end=shoulder
    refill=cylinder(v["refill_stem"]/2,stem_end-tip,tip)
    refill=refill.fuse(cylinder(v["refill_diameter"]/2,rear-shoulder,shoulder))
    add("refill",refill,"refill","purchased_refill",[211,158,69,255],"Purchased cartridge; verify envelope against supplier drawing",[18,0,0],True)

    guide=tube(v["guide_diameter"]/2,v["refill_stem"]/2+v["guide_bore_clearance"],v["guide_length"],spring_bottom)
    add("spring_guide",guide,"mechanism","acetal",[206,231,225,255],"Turn acetal guide; seat in nose",[-14,0,-14])
    washer=tube(v["seat_diameter"]/2,v["refill_stem"]/2+v["seat_bore_clearance"],v["seat_thickness"],seat_top)
    add("spring_seat",washer,"mechanism","acetal",[138,198,185,255],"Turn acetal thrust washer",[14,0,-8],True)

    # Two closely wound end turns plus the declared active turns. A spline joins
    # the pitch transitions; supplier must grind ends to the specified seats.
    active=v["spring_coils"]
    wire=v["spring_wire"]
    end_turns=v["spring_inactive_coils"]/2
    assert end_turns > 0
    total_turns=active+2*end_turns
    center_height=v["spring_installed"]-wire
    end_rise=wire*v["spring_end_pitch_factor"]*end_turns
    points=[]
    samples_per_turn=int(settings["spring_samples_per_turn"])
    assert samples_per_turn > 0
    for i in range(int(total_turns*samples_per_turn)+1):
        turn=i/samples_per_turn
        if turn<end_turns:
            z=end_rise*turn/end_turns
        elif turn<=end_turns+active:
            z=end_rise+(center_height-2*end_rise)*(turn-end_turns)/active
        else:
            z=center_height-end_rise+end_rise*(turn-end_turns-active)/end_turns
        theta=2*math.pi*turn
        points.append(cq.Vector(v["spring_mean"]/2*math.cos(theta),v["spring_mean"]/2*math.sin(theta),z))
    path=cq.Edge.makeSpline(points)
    plane=cq.Plane(origin=points[0],normal=points[1]-points[0])
    spring=cq.Workplane(plane).circle(wire/2).sweep(cq.Wire.assembleEdges([path]),isFrenet=True).val().translate((0,0,spring_bottom+wire/2))
    add("spring",spring,"spring","steel",[164,181,204,255],"Cold coil music wire; close and grind ends; stress relieve",[-18,0,0],True)

    add("rotor",cam_parts["rotor"],"mechanism","acetal",[242,154,76,255],f"Machine {profile.count} annular followers and {2*profile.count} triangular face cams",[18,0,14],True)
    add("cam_sleeve",cam_parts["cam_sleeve"],"mechanism","acetal",[109,126,241,255],"Mill return ramps, alternating stops, plunger guides, retaining collar and cap keys",[-18,0,16])
    add("button",cam_parts["button"],"mechanism","acetal",[57,200,173,255],"Machine guided button with opposing crown cams",[0,0,38],True)
    button_top=cam_datums["button_top_mm"]

    assembly=cq.Assembly(name="Closure_click_pen")
    scene=trimesh.Scene()
    metadata=[]
    for part in parts:
        shape=part["shape"]
        color=part["color"]
        assembly.add(shape,name=part["id"],color=cq.Color(*(x/255 for x in color)))
        vertices,faces=shape.tessellate(settings["mesh_linear_mm"],settings["mesh_angular_rad"])
        mesh=trimesh.Trimesh(vertices=np.array([p.toTuple() for p in vertices])*0.001,faces=np.array(faces),process=True)
        mesh.visual=trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(baseColorFactor=color,metallicFactor=0.8 if part["material"] in ("aluminum","steel") else 0.05,roughnessFactor=0.3))
        scene.add_geometry(mesh,node_name=part["id"],geom_name=part["id"])
        cq.exporters.export(shape,str(out/(part["id"]+".stl")),tolerance=settings["mesh_linear_mm"])
        shape.exportBrep(str(out/(part["id"]+".brep")))
        box=shape.BoundingBox()
        metadata.append({k:val for k,val in part.items() if k!="shape"} | {"volume_mm3":shape.Volume(),"valid":shape.isValid() and len(shape.Solids())==1,
                         "bounds_mm":[[box.xmin,box.ymin,box.zmin],[box.xmax,box.ymax,box.zmax]]})
    assembly.export(str(out/"click_pen.step"),"STEP")
    (out/"click_pen.glb").write_bytes(scene.export(file_type="glb"))
    import zipfile
    with zipfile.ZipFile(out/"parts_stl.zip","w",zipfile.ZIP_DEFLATED) as archive:
        for part in parts:
            archive.write(out/(part["id"]+".stl"),part["id"]+".stl")
    with zipfile.ZipFile(out/"parts_brep.zip","w",zipfile.ZIP_DEFLATED) as archive:
        for part in parts:
            archive.write(out/(part["id"]+".brep"),part["id"]+".brep")
    from assembly_motion import animation_metadata
    motion=json.loads(__import__('pathlib').Path(v["motion"]).read_text())
    animation=animation_metadata(motion,v["spring_installed"],spring_bottom)
    stock={"aluminum_mm3":math.pi*(diameter/2)**2*(length+nose_h+v["thread_engagement"]+v["cap_length"]+v["stock_allowance"])}
    assembly_data={"schema":"closure-assembly/0.1","name":"Click pen","length_unit":"mm","model_output":"model",
        "parts":metadata,"stock":stock,"cam_datums":cam_datums,**animation,
        "notes":["Threads are represented by mating envelopes; no released thread specification is supplied.",
                 "Motion follows rigid quasi-static cam contact envelopes. Friction is screened separately; dynamics, wear and lifetime require physical evidence. Spring rendering uses illustrative axial scaling.",
                 "Refill is a purchased-component envelope. Confirm shoulder and tip dimensions before procurement."]}
    (out/"assembly.json").write_text(json.dumps(assembly_data,indent=2))
    outputs={"model":artifact(out/"click_pen.glb","model/gltf-binary"),"step":artifact(out/"click_pen.step","model/step"),
             "native_parts":artifact(out/"parts_brep.zip","application/zip"),"assembly":artifact(out/"assembly.json","application/vnd.closure.assembly+json"),"stl_parts":artifact(out/"parts_stl.zip","application/zip"),
             "valid":s(all(p["valid"] for p in metadata)),"part_count":s(len(parts)), "length":q(button_top,"mm"),
             "spring_volume":q(next(p["volume_mm3"] for p in metadata if p["id"]=="spring"),"mm^3")}
write(request,outputs)
