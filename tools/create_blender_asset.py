"""Run with Blender to create the small, editable source asset for the example."""
import sys
from pathlib import Path
import bpy

destination = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
if destination.exists():
    raise RuntimeError("Source Blender asset already exists")
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
bpy.ops.mesh.primitive_cube_add(size=1, location=(.05, .05, .005))
domain = bpy.context.object
domain.name = "FluidDomain"
domain.dimensions = (.1, .1, .01)
material = bpy.data.materials.new("Fluid domain")
material.diffuse_color = (.09, .55, .72, 1)
domain.data.materials.append(material)
bpy.context.scene.unit_settings.system = "METRIC"
bpy.ops.wm.save_as_mainfile(filepath=str(destination))
