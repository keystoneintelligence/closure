"""Run inside Blender; load an actual .blend and export its evaluated dimensions."""
import json
import sys
from pathlib import Path
import bpy
from mathutils import Vector

arguments = sys.argv[sys.argv.index("--") + 1:]
request = json.loads(Path(arguments[0]).read_text(encoding="utf-8"))
inputs = request["inputs"]
output = Path(request["output_dir"])
bpy.ops.wm.open_mainfile(filepath=inputs["design"]["path"], load_ui=False, use_scripts=False)
domain = bpy.data.objects.get("FluidDomain")
if domain is None or domain.type != "MESH":
    raise ValueError("The linked Blender file must contain a mesh named FluidDomain")
domain.dimensions = [inputs[name]["value"] for name in ("length", "height", "depth")]
bpy.context.view_layer.update()
vertices = [domain.matrix_world @ Vector(corner) for corner in domain.bound_box]
sizes = [max(v[i] for v in vertices)-min(v[i] for v in vertices) for i in range(3)]
if any(size <= 0 for size in sizes):
    raise ValueError("Domain must have positive dimensions")
bpy.ops.wm.save_as_mainfile(filepath=str(output / "cavity.blend"))
bpy.ops.export_scene.gltf(filepath=str(output / "cavity.glb"), export_format="GLB")
manifest = {"blender_version": bpy.app.version_string, "build_hash": bpy.app.build_hash.decode(),
            "source_object": domain.name, "dimensions_m": sizes,
            "mesh_objects": len([o for o in bpy.data.objects if o.type == "MESH"]),
            "scope": "Evaluated bounding dimensions of a rectangular fluid-domain mesh."}
(output / "geometry.json").write_text(json.dumps(manifest, indent=2))
artifact = lambda name, media: {"path": str(output/name), "media_type": media}
response = {"protocol": "closure-run/0.1", "invocation_id": request["invocation_id"], "outputs": {
    "length": {"value": sizes[0], "unit": "m"}, "height": {"value": sizes[1], "unit": "m"}, "depth": {"value": sizes[2], "unit": "m"},
    "volume": {"value": sizes[0]*sizes[1]*sizes[2], "unit": "m^3"},
    "model": artifact("cavity.glb", "model/gltf-binary"), "blend": artifact("cavity.blend", "application/x-blender"),
    "inspection": artifact("geometry.json", "application/json")}}
Path(arguments[1]).write_text(json.dumps(response, allow_nan=False), encoding="utf-8")
