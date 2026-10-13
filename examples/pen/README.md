# Click pen engineering demonstrator

The editable Closure files are in [`model/`](model/); [`model/spring.yaml`](model/spring.yaml) is a compact starting point. They use the [source authoring standard](../../docs/AUTHORING_STANDARD.md). The [input-connection audit](../../docs/PEN_INPUT_AUDIT.md) explains which formerly local constants now flow through shared inputs and outputs, with their existing nominal values retained.

## Current checkpoint and scope

After the source readability and input-connection cleanup, forced verification `ec2b166c324d4a4c917a7ad453261687` reran all seven analyses and again supported 23 analytical obligations. All ten part volumes and bounds match the previous checkpoint within numerical comparison tolerances. The current model retains the same 140.5 mm length, 18.20391 g mass and 2.65746029 N peak button force; three physical tests remain open. This refactor connects existing values and does not introduce further mechanism optimization.

Further pen optimization was stopped at the user's request so development can focus on the general-purpose product. The final in-progress build (`a60b26f44ef1414e87f0c1585c887263`) completed with 23 analytical obligations supported, 140.5 mm length, 18.20 g mass and 2.657 N button force. Its cam motion is now computed from rigid contact envelopes; the exported B-rep audit checks 187 nominal poses. See the contact audit (development record). Three physical validation obligations remain open. Earlier concept-02 values and prescribed motion descriptions below describe that older exported snapshot, not this checkpoint. Subsequent engine edits may make current support stale; immutable build history preserves the original result.

Eight teams exchange typed dimensions, loads, material properties, and analysis results through Closure. The earlier concept-02 digital design produces ten CAD solids, a 139 mm assembled envelope, approximately 18.10 g finished mass, and 2.495 N calculated peak button force. Its 22 declared analytical concept obligations pass. Three physical validation obligations remain open.

Start from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,cad]"
.\.venv\Scripts\closure.exe verify --project examples/pen --trusted
.\.venv\Scripts\closure.exe serve --project examples/pen --workspace examples --trusted
```

Open `http://127.0.0.1:8765`. The viewer can orbit, explode, and show the assembly interior; select components and teams; inspect requirement evidence; and edit shared inputs before pressing **Verify**. Select **Rerun all** to execute every analysis in the selected context.

The concept 02 report (development record) is a portable snapshot with downloaded STEP, GLB, STL, bill of materials, and evidence records. Its artifact manifest (development record) maps output IDs to files and SHA256 hashes. Concept 01 is the earlier snapshot, before crown geometry was connected to the shared ramp and radius inputs. Rebuilding the project does not rewrite exported snapshots.

## Teams and interfaces

| Team | Owns | Supplies or consumes |
| --- | --- | --- |
| Product | Mass, length, force, material budgets | Authoritative requirement limits |
| Materials | Density, modulus, strength assumptions | Barrel, spring, mechanism, BOM inputs |
| Refill | Purchased cartridge envelope and mass | Tip, shoulder, spring seat, and rotor positions |
| Barrel | Housing dimensions and applied loads | Bore diameter, stress, deflection, structural margin |
| Spring | Wire, coil geometry, tolerances | Rate, preload, peak force, stress, fit envelope |
| Mechanism | Button, rotor, sleeve, travel | Force, clearance, torque, prescribed click states |
| Manufacturing | CAD generator and volume-based BOM | Geometry artifacts, mass, raw material quantity |
| Verification | Integrated criteria and physical test plan | Explicit concept scope and open test obligations |

Each team's source is in `model/`. Ordinary Python analyses in `analysis/` receive JSON and produce JSON/artifacts; none imports Closure. CAD is generated with CadQuery and exported through OpenCascade and trimesh.

## Engineering calculations

The barrel calculation uses a hollow circular beam under a central transverse load and a separate axial load. It calculates section area, second moment of area, combined elastic stress, yield safety factor, and simply supported deflection. The concept-02 inputs are 30 N transverse load, 20 N axial load, and 100 mm support span. The resulting safety factor is 18.43 and deflection is 0.0204 mm within that idealization.

The guided compression spring uses `k = G d⁴ / (8 D³ n)`, Wahl-corrected shear stress, rate and dimensional tolerances, and a conservative solid-height allowance. The concept-02 spring has 0.45 mm wire, 6.6 mm mean diameter, seven active coils plus two end coils, and a 15 mm installed length. Worst-case elastic shear factor is 1.64; remaining full-press solid clearance is 5.453 mm. The 1.85 fatigue factor is a screening calculation using assumed fatigue intercepts, not a demonstrated lifetime.

The mechanism analysis calculates button force, return torque, bearing stress, and dimensional clearances. CAD crown ramps consume the same 30 degree ramp angle and 3.1 mm mean contact radius as the force model. Its alternating click sequence is prescribed kinematics. The viewer illustrates those states; it is not a contact or friction solver.

Finished mass uses actual generated component volumes and declared densities, plus an assumed 3 g purchased refill. Raw aluminum stock is approximately 43.82 g. The geometry audit (development record) found no rigid-part volume intersections above 0.001 mm³ in the two nominal stable positions. It excludes the deformable spring and the transition path.

## Reproduce a failure across teams

In **Variables**, search for `spring.wire`, select **Edit / impact**, and change 0.45 to 0.55 mm. Closure shows affected elements in the spring, mechanism, manufacturing, product, and verification teams. Dependent requirements become stale while the barrel evidence remains current.

After **Build evidence**, peak button force is approximately 5.32 N against the 3 N limit. `mechanism.MEC-001` fails by approximately 2.32 N. Its explanation includes the path from `spring.wire` through `spring.response` and `mechanism.kinematics`. Return the input to 0.45 mm to recover the supported baseline; matching intact evidence can be reused.

Automated tests in `tests/test_pen.py` execute this change, check actual STEP/GLB components and material quantities, and confirm that physical tests remain open.

## Work required before physical release

This design has not been manufactured or physically tested. Complete the following work before treating it as a fabrication package:

- Resolve and verify the indexing cam's transition contacts, return ramp geometry, anti-rotation constraints, and the full press/release path. Two noninterfering end positions and a prescribed state sequence do not establish self-indexing behavior.
- Detail the nose/cap threads, retention and assembly process. The CAD contains mating envelopes; no released thread drawing is supplied.
- Obtain the actual refill drawing and measured friction, material, spring, and manufacturing tolerances.
- Verify spring seating and ground ends, writing loads, local contact stresses, creep, wear, and drop behavior.
- Execute `verification.TEST-001` through `TEST-003`: 10,000 click cycles, structural/writing/drop tests, and dimensional inspection.

The concept policy explicitly excludes those physical obligations and keeps them visible as missing evidence. Changing that policy or weakening a requirement invalidates the reviewed baseline.

Material and design references for subsequent qualification include [Lee Spring design considerations](https://www.leespring.it/sites/default/files/pdf/Lee%20Spring%20-%20WhitePaper%20-%20Spring%20Design%20General%20Consideration_US.pdf), [Kaiser aluminum data](https://online.kaiseraluminum.com/depot/PublicProductInformation/Document/1006/Kaiser_Aluminum_Shapes_Soft_Alloy.pdf), [Delrin data](https://www.delrin.com/wp-content/uploads/2024/07/Delrin-500CPE-Product-Data-Sheet-NA-revFNL.pdf), and the [Schmidt refill catalog](https://www.schmidttechnology.de/wp-content/uploads/2023/03/Schmidt-Writing-Instruments-Technology-Catalog.pdf). The exact supplied parts and allowables still need selection and validation.

Public source archives omit development evidence stores and generated deliverables. Run Verify in your environment, then `closure export --output NEW_FOLDER` to create an inspectable report from your own run.
