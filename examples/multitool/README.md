# Blender Python and OpenFOAM integration

This project runs a real Blender asset, an ordinary Python analysis, and an OpenFOAM transient simulation through Closure's language-neutral runner protocol. Three teams exchange typed values and retain the applications' native files as evidence.

| Team | Owns | Supplies |
|---|---|---|
| Design | `assets/domain.blend`, domain dimensions, Blender export | Evaluated dimensions, volume, GLB, updated Blender file |
| Analysis | Lid speed, assumed viscosity, transient duration, Python scaling | Reynolds number and shared physical inputs |
| CFD | OpenFOAM source case and execution adapter | Mesh check, solver diagnostics, velocity field, complete case archive |

Blender evaluates the `FluidDomain` mesh at the requested dimensions. Its measured bounding dimensions feed both Python's `Re = U L / nu` calculation and OpenFOAM's block mesh. Editing the source `.blend`, dimensions, case, script, or declared executable changes the relevant execution identity. No analysis imports Closure.

## Run on the verified Windows toolchain

The demonstrated environment uses Blender 4.3.2 and WSL Ubuntu 24.04 with the Ubuntu `openfoam` package, version `1912.200626-2build3`. The WSL distribution name is the `distribution` setting in `model/fluid.yaml`.

From the repository root, point Closure at your Blender executable:

```powershell
$env:CLOSURE_TOOL_BLENDER=(Get-Command blender).Source
.\.venv\Scripts\closure.exe check --project examples/multitool
.\.venv\Scripts\closure.exe build --project examples/multitool --trusted
.\.venv\Scripts\closure.exe serve --project examples/multitool --workspace examples --trusted
```

For an Ubuntu installation without OpenFOAM, install its distribution package inside WSL:

```powershell
wsl.exe -d Ubuntu --user root --exec apt-get update
wsl.exe -d Ubuntu --user root --exec apt-get install -y --no-install-recommends openfoam
```

The adapter uses `wslpath` to translate the frozen project paths, sets `WM_PROJECT_DIR=/usr/share/openfoam` and `WM_PROJECT=OpenFOAM`, and calls Linux Python to run `blockMesh`, `checkMesh`, and `icoFoam`. These paths match the verified Ubuntu package layout. Other OpenFOAM distributions or operating systems need a corresponding adapter; the Closure core and JSON exchange do not depend on WSL.

## Evidence and scope

The nominal domain is 0.1 × 0.1 × 0.01 m with a 1 m/s moving lid, an assumed kinematic viscosity of 0.001 m²/s, and a 20 × 20 × 1 mesh. The simulation takes 500 steps of 0.002 s. The case is synthetic and intentionally small.

The recorded nominal run passed seven declared requirements:

| Result | Observed value |
|---|---:|
| Reynolds number | Approximately 100 |
| Final simulation time | 1 s |
| Internal cells | 400 |
| Maximum Courant number over the run | 0.3359112295 |
| Maximum final linear-solver residual | 9.999049522e-8 |
| Absolute cumulative continuity error | 1.498584079e-17 |
| Maximum internal velocity | 0.8403631903 m/s |
| Cells with negative x velocity | 323 |

The exported case retains the actual mesh, pressure and velocity fields, dictionaries, `cavity.foam` marker, and solver logs. `flow.json` records the Linux solver executable hashes and package version; `geometry.json` records Blender's version and build hash. Closure's record captures source hashes, inputs, tool paths and executable hashes, upstream provenance, and context.

The solver completion flag covers finite diagnostics and the declared linear-residual threshold. It does not establish a steady state, grid independence, turbulence validity, or agreement with physical measurements. The recirculation criterion checks that negative-x flow cells exist; it is not a benchmark error comparison.

## Historical results and cache reuse

Blender's bundled libraries and the WSL OpenFOAM runtime are not isolated or completely fingerprinted. Both adapters declare those uncontrolled dependencies, so Closure deliberately reruns them on each build. A later plan cannot present their old evidence as current.

The Linux launcher also imposes a 165-second guest-process deadline, followed by forced termination after a five-second grace period. This bounds an orphaned guest run independently if its Windows bridge disappears. Windows job cleanup alone cannot guarantee immediate cancellation inside WSL.

After a build, the viewer opens its historical snapshot. The banner and read-only controls distinguish recorded support from the current project. Use **Evidence → Open snapshot** to revisit a saved build, or **Inspect run** to inspect one analysis. **Return to current project** shows the conservative freshness assessment.

To export a recorded build without rerunning the applications:

```powershell
.\.venv\Scripts\closure.exe history --project examples/multitool --json
.\.venv\Scripts\closure.exe export --project examples/multitool --report REPORT_ID --output reports/cavity-review
```

Replace `REPORT_ID` with an ID from history and choose a new output folder. The recorded integration report (development record) includes the five produced artifacts and the consumed source Blender file, each with a verified content hash.

## Integration regression

```powershell
$env:CLOSURE_TOOL_BLENDER=(Get-Command blender).Source
$env:CLOSURE_RUN_EXTERNAL_TOOLS='1'
.\.venv\Scripts\python.exe -m pytest tests/test_multitool.py -q
```

The test copies the project into an isolated directory, runs the installed applications, independently reads all 400 velocity vectors and the 500-step log, then changes the domain length to 0.08 m. It verifies that Blender's evaluated length reaches both the OpenFOAM dictionary and the Python result, changing the Reynolds number to approximately 80. It also verifies that read-only planning runs no tool, and that the original 0.1 m build remains available as historical evidence.

Public source archives omit development evidence stores and generated deliverables. Run Verify in your environment, then `closure export --output NEW_FOLDER` to create an inspectable report from your own run.
