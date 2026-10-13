"""Create the initial editable pen contracts. Refuses to overwrite existing work."""
from pathlib import Path
from ruamel.yaml import YAML

ROOT=Path(__file__).resolve().parents[1]/"examples"/"pen"
YAML_WRITER=YAML()
YAML_WRITER.default_flow_style=False
YAML_WRITER.width=110


def save(path,value):
    path=ROOT/path
    if path.exists():
        raise RuntimeError(f"Refusing to overwrite {path}")
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8") as stream:
        YAML_WRITER.dump(value,stream)


def datum(value,unit=None,description="",assumption=False):
    result={"value":value,"description":description}
    if unit: result["unit"]=unit
    if assumption:
        result.update(origin="assumption",rationale=description)
    return result


def team(name,title,owner,color,description,parameters):
    return {"schema":"closure/0.1","module":name,"name":title,"owner":owner,"color":color,"description":description,
            "parameters":parameters,"analyses":{},"requirements":{},"exports":list(parameters)}


def analysis(module,name,script,inputs,outputs,description):
    bindings={key:{"ref":ref,**({"unit":unit} if unit else {})} for key,(ref,unit) in inputs.items()}
    ports={key:({"type":unit} if unit in ("artifact","boolean","scalar") else {"type":"quantity","unit":unit}) for key,unit in outputs.items()}
    module["analyses"][name]={"description":description,"run":{"argv":["python",f"analysis/{script}.py"],"sources":[f"analysis/{script}.py"],"timeout":240},"inputs":bindings,"outputs":ports}
    module["exports"].extend(f"{name}.{key}" for key in outputs)


def criterion(ref,op,value,unit=None):
    limit={"ref":value} if isinstance(value,str) and "." in value else datum(value,unit)
    return {"actual":{"ref":ref},"op":op,"limit":limit}


def requirement(module,key,text,ref,op,value,unit=None,**kwargs):
    module["requirements"][key]={"text":text,"verify":criterion(ref,op,value,unit),**kwargs}


product=team("product","Product & requirements","Product engineering","#60a5fa","Defines the user's pen experience and the concept acceptance scope.",{
    "max_mass":datum(22,"g","Finished pen mass target"),"max_length":datum(145,"mm"),"max_force":datum(3,"N"),
    "min_force":datum(1,"N"),"bending_load":datum(30,"N","Midspan transverse qualification load"),
    "bending_span":datum(100,"mm","Simply supported test span"),"axial_load":datum(20,"N","Axial writing/handling design load"),
    "max_stock_mass":datum(50,"g","Aluminum raw-stock mass budget")})
materials=team("materials","Materials & allowables","Materials engineering","#b391f4","Supplier properties and explicitly assumed design allowables.",{
    "aluminum_density":datum(2.70,"g/cm^3","6061 density; procurement confirmation required",True),
    "aluminum_modulus":datum(69000,"MPa","6061 elastic modulus for room-temperature concept analysis",True),
    "aluminum_yield":datum(200,"MPa","Conservative 6061-T6 design yield; confirm product form and material certificate",True),
    "acetal_density":datum(1.42,"g/cm^3","Delrin 500P/500CPE typical supplier density",True),
    "acetal_bearing":datum(25,"MPa","Conservative short-duration acetal bearing allowable; creep/wear not covered",True),
    "steel_density":datum(7.85,"g/cm^3","Music-wire density assumption",True),
    "steel_shear_modulus":datum(79300,"MPa","Room-temperature music-wire shear modulus assumption",True),
    "spring_shear_allowable":datum(650,"MPa","Derated elastic shear allowable pending wire supplier confirmation",True),
    "spring_alternating":datum(350,"MPa","Assumed fatigue-screening alternating shear intercept; life test remains open",True),
    "spring_mean":datum(900,"MPa","Assumed fatigue-screening mean shear intercept",True)})
refill=team("refill","Ink & refill","Writing systems","#eab86a","Purchased cartridge envelope; supplier dimensions remain a procurement check.",{
    "length":datum(98.1,"mm","Provisional purchased refill length",True),"diameter":datum(5.8,"mm","Cartridge body envelope",True),
    "stem":datum(2.3,"mm","Front stem envelope",True),"shoulder":datum(27,"mm","Tip-to-body shoulder distance; confirm with selected refill",True),
    "mass":datum(3,"g","Purchased filled cartridge mass assumption",True),"retracted_gap":datum(1.5,"mm"),
    "axial_stack_tolerance":datum(0.25,"mm","Combined cartridge and housing axial tolerance",True)})
barrel=team("barrel","Barrel & housing","Mechanical structures","#45a7c4","Turned aluminum housing and its elastic structural checks.",{
    "diameter":datum(12,"mm"),"wall":datum(0.8,"mm"),"length":datum(106,"mm"),"nose_length":datum(18,"mm"),
    "nose_tip_diameter":datum(4.8,"mm"),"tip_bore":datum(2.7,"mm"),"spring_cavity":datum(7.6,"mm"),
    "thread_engagement":datum(5.5,"mm","Threaded joint axial engagement; CAD uses cosmetic envelopes"),"cap_length":datum(10,"mm")})
analysis(barrel,"strength","barrel",{k:(f"barrel.{k}","mm") for k in ("diameter","wall","length")} | {
    "span":("product.bending_span","mm"),"bending_load":("product.bending_load","N"),"axial_load":("product.axial_load","N"),
    "yield_strength":("materials.aluminum_yield","MPa"),"modulus":("materials.aluminum_modulus","MPa")},
    {"inner_diameter":"mm","area":"mm^2","inertia":"mm^4","stress":"MPa","deflection":"mm","safety_factor":"scalar","volume":"mm^3"},
    "Simply supported 30 N bending case with conservative additive axial stress.")
requirement(barrel,"STR-001","Barrel yield safety factor shall be at least 3 under the declared loads.","barrel.strength.safety_factor","gte",3)
requirement(barrel,"STR-002","Midspan elastic deflection shall be no more than 0.5 mm.","barrel.strength.deflection","lte",0.5,"mm")
spring=team("spring","Return spring","Spring engineering","#e694bb","Guided compression spring, tolerance envelope and fatigue screening.",{
    "wire":datum(0.45,"mm"),"mean_diameter":datum(6.6,"mm"),"active_coils":datum(7),"free_length":datum(18,"mm"),
    "installed_length":datum(15,"mm"),"rate_tolerance":datum(0.10,"dimensionless","Relative spring-rate envelope",True),
    "length_tolerance":datum(0.10,"mm",assumption=True),"wire_tolerance":datum(0.01,"mm",assumption=True),"diameter_tolerance":datum(0.05,"mm",assumption=True)})
spring_inputs={k:(f"spring.{k}","mm" if k not in ("active_coils","rate_tolerance") else None) for k in spring["parameters"]}
spring_inputs.update(stroke=("mechanism.full_stroke","mm"),shear_modulus=("materials.steel_shear_modulus","MPa"),
                     shear_allowable=("materials.spring_shear_allowable","MPa"),alternating_allowable=("materials.spring_alternating","MPa"),mean_allowable=("materials.spring_mean","MPa"))
analysis(spring,"response","spring",spring_inputs,{"rate":"N/mm","preload_force":"N","peak_force":"N","worst_force":"N","shear_stress":"MPa",
    "safety_factor":"scalar","fatigue_factor":"scalar","solid_clearance":"mm","solid_height":"mm","outer_diameter":"mm","inner_diameter":"mm","volume":"mm^3","curve":"artifact"},
    "Linear helical spring with Wahl correction, tolerances and an assumed Goodman fatigue envelope.")
requirement(spring,"SPR-001","Worst-case elastic shear safety factor shall be at least 1.5.","spring.response.safety_factor","gte",1.5)
requirement(spring,"SPR-002","Full press shall retain at least 1 mm clearance above worst-case solid height.","spring.response.solid_clearance","gte",1,"mm")
requirement(spring,"SPR-003","Assumed fatigue-screening factor shall be at least 1.5.","spring.response.fatigue_factor","gte",1.5)
mechanism=team("mechanism","Click mechanism","Mechanism engineering","#36c8ac","Three-lug rotating follower, alternating-depth cam sleeve and guided push button.",{
    "full_stroke":datum(5,"mm"),"travel":datum(3,"mm"),"ramp_angle":datum(30,"degree"),"friction_coefficient":datum(0.15,description="Assumed bounded sliding coefficient; measure on prototype",assumption=True),
    "sliding_friction":datum(0.2,"N",assumption=True),"cam_radius":datum(3.1,"mm"),"lug_count":datum(3),"lug_width":datum(1.4,"mm"),
    "lug_depth":datum(0.8,"mm"),"lug_height":datum(1.4,"mm"),"lug_offset":datum(1.4,"mm"),"slot_width":datum(1.8,"mm"),
    "machining_tolerance":datum(0.05,"mm",assumption=True),"tooth_height":datum(1.2,"mm"),"guide_diameter":datum(5.8,"mm"),
    "guide_length":datum(10,"mm"),"sleeve_diameter":datum(9.9,"mm"),"rotor_diameter":datum(7.8,"mm"),"rotor_clearance":datum(0.4,"mm"),
    "rotor_stem":datum(4.2,"mm"),"rotor_stem_length":datum(9,"mm"),"rotor_head_height":datum(4,"mm"),
    "seat_diameter":datum(7.5,"mm"),"seat_thickness":datum(1,"mm"),"button_shaft":datum(5.8,"mm"),"button_diameter":datum(8.8,"mm"),
    "button_projection":datum(5,"mm"),"release_gap":datum(0.3,"mm")})
mechanism_inputs={k:(f"mechanism.{k}",("degree" if k=="ramp_angle" else "N" if k=="sliding_friction" else None if k in ("lug_count","friction_coefficient") else "mm"))
                  for k in ("full_stroke","travel","ramp_angle","friction_coefficient","sliding_friction","cam_radius","lug_count","lug_width","lug_depth","slot_width","machining_tolerance","tooth_height","guide_diameter","sleeve_diameter")}
mechanism_inputs.update(spring_peak=("spring.response.worst_force","N"),spring_preload=("spring.response.preload_force","N"),spring_inner=("spring.response.inner_diameter","mm"),
                        barrel_inner=("barrel.strength.inner_diameter","mm"),bearing_allowable=("materials.acetal_bearing","MPa"),retracted_gap=("refill.retracted_gap","mm"),axial_stack_tolerance=("refill.axial_stack_tolerance","mm"))
analysis(mechanism,"kinematics","mechanism",mechanism_inputs,{"push_force":"N","return_torque":"N*mm","bearing_stress":"MPa","bearing_factor":"scalar","slot_clearance":"mm",
    "release_clearance":"mm","guide_clearance":"mm","sleeve_clearance":"mm","tip_extension":"mm","tip_retraction":"mm","cycle_valid":"boolean","cycle":"artifact"},
    "Quasi-static force/clearance calculation and prescribed alternating click state model.")
for key,text,out_name,op,value,unit in [
    ("MEC-001","Peak button force shall not exceed the product limit.","push_force","lte","product.max_force",None),
    ("MEC-002","Peak button force shall exceed the minimum tactile-force target.","push_force","gte","product.min_force",None),
    ("MEC-003","Return torque margin shall exceed 0.3 N mm.","return_torque","gte",0.3,"N*mm"),
    ("MEC-004","Worst-case follower slot clearance shall be at least 0.1 mm.","slot_clearance","gte",0.1,"mm"),
    ("MEC-005","Cam release overtravel shall retain at least 0.5 mm.","release_clearance","gte",0.5,"mm"),
    ("MEC-006","Spring guide diametral clearance shall be at least 0.1 mm.","guide_clearance","gte",0.1,"mm"),
    ("MEC-007","Mechanism sleeve shall retain at least 0.1 mm diametral housing clearance.","sleeve_clearance","gte",0.1,"mm"),
    ("MEC-008","Extended tip shall project at least 1 mm.","tip_extension","gte",1,"mm"),
    ("MEC-009","Retracted tip shall remain at least 0.8 mm inside the nose at worst stack.","tip_retraction","gte",0.8,"mm"),
    ("MEC-010","The prescribed click cycle shall alternate between two stable states.","cycle_valid","eq",True,None),
    ("MEC-011","Cam bearing safety factor shall be at least 3.","bearing_factor","gte",3,None)]:
    requirement(mechanism,key,text,f"mechanism.kinematics.{out_name}",op,value,unit)

manufacturing=team("manufacturing","CAD & manufacturing","Manufacturing engineering","#ed9660","Builds the actual solids and derives material quantities from their volumes.",{})
cad_inputs={}
for prefix,names in {"barrel":["diameter","length","nose_length","nose_tip_diameter","tip_bore","spring_cavity","thread_engagement","cap_length"],
                     "refill":["length","diameter","stem","shoulder","retracted_gap"],
                     "spring":["wire","mean_diameter","active_coils","installed_length"]}.items():
    for name in names:
        alias={"barrel.diameter":"barrel_diameter","barrel.length":"barrel_length","refill.length":"refill_length","refill.diameter":"refill_diameter","refill.stem":"refill_stem","refill.shoulder":"refill_shoulder",
               "spring.wire":"spring_wire","spring.mean_diameter":"spring_mean","spring.active_coils":"spring_coils","spring.installed_length":"spring_installed"}.get(f"{prefix}.{name}",name)
        cad_inputs[alias]=(f"{prefix}.{name}",None if name=="active_coils" else "mm")
for name in ("tooth_height","full_stroke","travel","rotor_stem","rotor_stem_length","rotor_diameter","rotor_head_height","lug_offset","lug_depth","lug_width","lug_height","sleeve_diameter","rotor_clearance","slot_width","button_shaft","button_diameter","button_projection","release_gap","seat_diameter","seat_thickness","guide_diameter","guide_length"):
    cad_inputs[name]=(f"mechanism.{name}","mm")
cad_inputs["ramp_angle"]=("mechanism.ramp_angle","degree")
cad_inputs["cam_radius"]=("mechanism.cam_radius","mm")
cad_inputs["barrel_inner"]=("barrel.strength.inner_diameter","mm")
analysis(manufacturing,"cad","cad",cad_inputs,{"model":"artifact","step":"artifact","assembly":"artifact","stl_parts":"artifact","valid":"boolean","part_count":"scalar","length":"mm","spring_volume":"mm^3"},"Generate ten named B-rep solids, STEP, GLB, STL parts, and a general-purpose assembly manifest.")
analysis(manufacturing,"materials","bom",{"assembly":("manufacturing.cad.assembly",None),"aluminum_density":("materials.aluminum_density","g/cm^3"),
    "acetal_density":("materials.acetal_density","g/cm^3"),"steel_density":("materials.steel_density","g/cm^3"),"refill_mass":("refill.mass","g")},
    {"mass":"g","aluminum_volume":"mm^3","raw_aluminum_mass":"g","material_yield":"percent","bom":"artifact","bom_csv":"artifact"},"Compute purchased and manufactured material quantities from actual CAD solid volumes.")
requirement(manufacturing,"CAD-001","Every generated component shall be a valid positive-volume solid.","manufacturing.cad.valid","eq",True)
requirement(manufacturing,"CAD-002","Assembly shall contain the ten specified components.","manufacturing.cad.part_count","eq",10)
requirement(manufacturing,"MFG-001","Raw aluminum stock shall remain within the product material budget.","manufacturing.materials.raw_aluminum_mass","lte","product.max_stock_mass")
requirement(product,"PRD-001","Finished pen mass shall be within the product target.","manufacturing.materials.mass","lte","product.max_mass")
requirement(product,"PRD-002","Retracted overall length shall fit the product envelope.","manufacturing.cad.length","lte","product.max_length")
verification=team("verification","Verification & acceptance","Systems verification","#a4b6c9","Records concept closure and the physical validation still required before manufacture.",{})
verification["requirements"]["SYS-001"]={"text":"The integrated digital design shall meet CAD, force, mass, travel, and structural criteria together.",
    "verify":{"all_of":[criterion("manufacturing.cad.valid","eq",True),criterion("manufacturing.materials.mass","lte","product.max_mass"),
        criterion("barrel.strength.safety_factor","gte",3),criterion("spring.response.safety_factor","gte",1.5),
        criterion("mechanism.kinematics.push_force","lte","product.max_force"),criterion("mechanism.kinematics.cycle_valid","eq",True)]}}
for key,text in [("TEST-001","Prototype shall pass 10,000 physical click cycles without jamming or unintended release."),
                 ("TEST-002","Manufactured pen shall pass the specified bending, writing and drop tests."),
                 ("TEST-003","Purchased refill, spring and manufactured interfaces shall pass dimensional inspection.")]:
    verification["requirements"][key]={"text":text,"method":"test" if key!="TEST-003" else "inspection","required":False,"review_required":True}
for module in (product,materials,refill,barrel,spring,mechanism,manufacturing,verification):
    save(Path("model")/(module["module"]+".yaml"),module)
save(Path("project.yaml"),{"schema":"closure/0.1","project":"click-pen","name":"Click / engineering demonstrator",
    "description":"A retractable pen designed by eight cooperating teams. Analytical concept gate; physical validation obligations remain visible.",
    "modules":["model/*.yaml"],"policy":{"name":"analytical-concept","accepted_evidence":["assumed","predicted"],
    "description":"Accept deterministic analytical and CAD evidence under explicitly declared assumptions. Manufacturing release requires physical tests."}})
save(Path("studies/spring_trade.yaml"),{"schema":"closure/0.1","study":"spring-wire-trade","grid":{
    "spring.wire":[datum(x,"mm") for x in (0.40,0.45,0.55)],"mechanism.friction_coefficient":[datum(x) for x in (0.10,0.25)]}})
print(f"Created pen contracts in {ROOT}")
