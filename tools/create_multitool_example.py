"""Create the editable contracts and OpenFOAM case for the real-tool example."""
from pathlib import Path
from ruamel.yaml import YAML

root = Path(__file__).resolve().parents[1] / "examples/multitool"
yaml = YAML()
def save(path, value):
    target = root / path
    if target.exists():
        raise RuntimeError(f"Refusing to overwrite {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as stream:
        yaml.dump(value, stream)
def q(value, unit=None):
    return {"value": value, **({"unit": unit} if unit else {})}
def ref(name, unit=None):
    return {"ref": name, **({"unit": unit} if unit else {})}
def port(kind):
    return {"type": kind} if kind in ("scalar", "boolean", "artifact") else {"type": "quantity", "unit": kind}
def requirement(text, actual, op, limit):
    return {"text": text, "verify": {"actual": ref(actual), "op": op, "limit": limit}}

save("project.yaml", {"schema": "closure/0.1", "project": "blender-openfoam", "name": "Cavity / connected tools",
    "description": "A real Blender file supplies geometry to Python and an OpenFOAM transient flow case.",
    "modules": ["model/*.yaml"], "policy": {"name": "integration-demonstration", "accepted_evidence": ["assumed", "predicted"],
    "description": "Checks tool-chain execution and declared numerical criteria; no steady-state or physical validation claim."}})
geometry_outputs = {k: port(v) for k,v in {"length":"m", "height":"m", "depth":"m", "volume":"m^3", "model":"artifact", "blend":"artifact", "inspection":"artifact"}.items()}
save("model/geometry.yaml", {"schema":"closure/0.1", "module":"geometry", "name":"Blender geometry", "owner":"Design team", "color":"#8f77de",
    "parameters":{"design":{"type":"artifact","path":"assets/domain.blend"}, "length":q(.1,"m"), "height":q(.1,"m"), "depth":q(.01,"m")},
    "analyses":{"export":{"description":"Load an actual Blender asset, apply dimensions and export GLB, blend and measured envelope.",
        "run":{"argv":["python","analysis/blender_driver.py"], "sources":["analysis/blender_driver.py","analysis/blender_scene.py"],
               "tools":{"blender":"blender"}, "timeout":120,
               "uncontrolled_dependencies":["Blender's bundled exporters and runtime libraries are not independently fingerprinted; reuse is disabled."]},
        "inputs":{k:ref("geometry."+k, "m" if k!="design" else None) for k in ("design","length","height","depth")}, "outputs":geometry_outputs}},
    "requirements":{"GEO-001":requirement("Fluid-domain envelope volume shall be positive.", "geometry.export.volume", "gt", q(0,"m^3"))},
    "exports":["export."+k for k in geometry_outputs]})
save("model/physics.yaml", {"schema":"closure/0.1", "module":"physics", "name":"Python fluid scaling", "owner":"Analysis team", "color":"#30b897",
    "parameters":{"lid_speed":q(1,"m/s"), "viscosity":{**q(.001,"m^2/s"),"origin":"assumption","rationale":"Synthetic laminar fluid for the Re=100 cavity example."},
        "end_time":q(1,"s"), "time_step":q(.002,"s"), "max_reynolds":q(200)},
    "analyses":{"scaling":{"run":{"argv":["python","analysis/dimensionless.py"],"sources":["analysis/dimensionless.py"]},
        "inputs":{"length":ref("geometry.export.length","m"),"lid_speed":ref("physics.lid_speed","m/s"),"viscosity":ref("physics.viscosity","m^2/s")},
        "outputs":{"reynolds":port("scalar")}}},
    "requirements":{"FLOW-001":requirement("The example shall remain within its declared low-Reynolds-number scope.","physics.scaling.reynolds","lte",ref("physics.max_reynolds"))},
    "exports":["lid_speed","viscosity","end_time","time_step","scaling.reynolds"]})
fluid_outputs={k:port(v) for k,v in {"mesh_valid":"boolean","cells":"scalar","final_time":"s","max_courant":"scalar","continuity_error":"scalar","max_velocity":"m/s","recirculating_cells":"scalar","diagnostics":"artifact","case":"artifact"}.items()}
save("model/fluid.yaml", {"schema":"closure/0.1", "module":"fluid", "name":"OpenFOAM simulation", "owner":"CFD team", "color":"#e39c52",
    "analyses":{"cavity":{"description":"Execute blockMesh, checkMesh and icoFoam in WSL, with geometry bound from Blender.",
        "run":{"argv":["python","analysis/openfoam_driver.py"],"sources":["analysis/openfoam_driver.py","analysis/openfoam_worker.py","analysis/openfoam_environment.sh","case/"],
               "tools":{"wsl":"wsl.exe"},"timeout":240,"max_output_bytes":2000000,
               "uncontrolled_dependencies":["WSL distribution and OpenFOAM shared libraries are not isolated; tool hashes are recorded at execution and reuse is disabled."]},
        "solver":True,"settings":{"distribution":"Ubuntu"},
        "inputs":{**{k:ref("geometry.export."+k,"m") for k in ("length","height","depth")},
                  **{k:ref("physics."+k,u) for k,u in {"lid_speed":"m/s","viscosity":"m^2/s","end_time":"s","time_step":"s"}.items()}},
        "outputs":fluid_outputs}},
    "requirements":{
        "CFD-001":requirement("OpenFOAM mesh quality checks shall pass.","fluid.cavity.mesh_valid","eq",q(True)),
        "CFD-002":requirement("Maximum Courant number shall stay below 0.5.","fluid.cavity.max_courant","lte",q(.5)),
        "CFD-003":requirement("Absolute cumulative continuity error shall not exceed 1e-6.","fluid.cavity.continuity_error","lte",q(1e-6)),
        "CFD-004":requirement("Solver shall reach the requested transient duration.","fluid.cavity.final_time","gte",ref("physics.end_time")),
        "CFD-005":requirement("The cavity shall contain recirculating internal flow cells.","fluid.cavity.recirculating_cells","gt",q(0))},
    "exports":["cavity."+k for k in fluid_outputs]})

header = lambda kind, obj: f'FoamFile\n{{\n    version 2.0;\n    format ascii;\n    class {kind};\n    object {obj};\n}}\n'
files = {
"case/closureParameters": "L 0.1;\nH 0.1;\nD 0.01;\nlidVelocity (1 0 0);\nkinematicViscosity 0.001;\nendTimeValue 1;\ndeltaTValue 0.002;\n",
"case/system/blockMeshDict": header("dictionary","blockMeshDict") + '''#include "../closureParameters"
convertToMeters 1;
vertices ((0 0 0) ($L 0 0) ($L $H 0) (0 $H 0) (0 0 $D) ($L 0 $D) ($L $H $D) (0 $H $D));
blocks (hex (0 1 2 3 4 5 6 7) (20 20 1) simpleGrading (1 1 1));
edges ();
boundary
(
    movingWall { type wall; faces ((3 7 6 2)); }
    fixedWalls { type wall; faces ((0 4 7 3) (2 6 5 1) (1 5 4 0)); }
    frontAndBack { type empty; faces ((0 3 2 1) (4 5 6 7)); }
);
mergePatchPairs ();
''',
"case/system/controlDict": header("dictionary","controlDict") + '''#include "../closureParameters"
application icoFoam;
startFrom startTime;
startTime 0;
stopAt endTime;
endTime $endTimeValue;
deltaT $deltaTValue;
writeControl runTime;
writeInterval $endTimeValue;
purgeWrite 0;
writeFormat ascii;
writePrecision 10;
writeCompression off;
timeFormat general;
timePrecision 10;
runTimeModifiable false;
''',
"case/system/fvSchemes": header("dictionary","fvSchemes") + '''ddtSchemes { default Euler; }
gradSchemes { default Gauss linear; grad(p) Gauss linear; }
divSchemes { default none; div(phi,U) Gauss linear; }
laplacianSchemes { default Gauss linear orthogonal; }
interpolationSchemes { default linear; }
snGradSchemes { default orthogonal; }
fluxRequired { default no; p; }
''',
"case/system/fvSolution": header("dictionary","fvSolution") + '''solvers
{
    p { solver PCG; preconditioner DIC; tolerance 1e-7; relTol 0; }
    pFinal { $p; relTol 0; }
    U { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-8; relTol 0; }
}
PISO { nCorrectors 2; nNonOrthogonalCorrectors 0; pRefCell 0; pRefValue 0; }
''',
"case/constant/transportProperties": header("dictionary","transportProperties") + '''#include "../closureParameters"
nu [0 2 -1 0 0 0 0] $kinematicViscosity;
''',
"case/0/U": header("volVectorField","U") + '''#include "../closureParameters"
dimensions [0 1 -1 0 0 0 0];
internalField uniform (0 0 0);
boundaryField
{
    movingWall { type fixedValue; value uniform $lidVelocity; }
    fixedWalls { type fixedValue; value uniform (0 0 0); }
    frontAndBack { type empty; }
}
''',
"case/0/p": header("volScalarField","p") + '''dimensions [0 2 -2 0 0 0 0];
internalField uniform 0;
boundaryField
{
    movingWall { type zeroGradient; }
    fixedWalls { type zeroGradient; }
    frontAndBack { type empty; }
}
'''}
for name, text in files.items():
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")
(root/"assets").mkdir(exist_ok=True)
