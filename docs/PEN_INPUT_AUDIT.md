# Pen input connections

The pen had a sound dependency chain for its primary engineering calculations, but its claim that every CAD dimension came from team contracts was too strong. Several fit details, manufacturing allowances and numerical settings lived as unexplained literals inside wrappers. Those values are now explicit inputs or recorded analysis settings, preserving their existing nominal values.

## Existing strengths

Product loads and targets, material properties, major geometry, refill dimensions and spring dimensions were already owned by modules and passed into analyses. Solved cam travel fed the spring calculation; spring force fed the mechanism screen; CAD volumes fed the material budget. Requirement checks consumed exported results. Changing spring wire already propagated across teams and could fail the button-force requirement.

## Connections corrected

| Previous local constant | Current source and consumers |
| --- | --- |
| Cam ring half-width `0.7` repeated in CAD and slope screening | `mechanism.crown_width` supplies both CAD and motion screening; each derives half-width |
| Two inactive spring turns repeated in calculations and CAD | `spring.inactive_coils` supplies both; the CAD divides the total between its two ends |
| Spring solid-height multiplier and end-turn pitch multiplier | Separate explained assumptions `spring.solid_height_factor` and `spring.end_pitch_factor` |
| Cap engagement and sleeve position both assumed 2 mm | `barrel.cap_spigot_length` controls the cap and retained sleeve top |
| Independently coded key and cap-pocket dimensions | Named key dimensions plus clearance; pocket dimensions derive from the mating key and cap engagement |
| Housing, guide, seat, plunger and follower fit details | Named barrel/mechanism parameters passed into CAD and its imported cam helper |
| Raw-stock allowance of 4 mm | `manufacturing.stock_allowance` flows through CAD stock metadata into the BOM budget |
| Fixed 120-degree animation normalization | Motion exports `rotational_period_deg`, derived from follower count; animation consumes it |
| Motion step sizes, convergence tolerance, mesh resolution and contact sampling | Explicit analysis `settings`, retained in execution identity and evidence |
| Declared force-wrapper inputs that were never read | Three unused bindings removed; their source parameters and genuine consumers remain |

There are no intentional changes to nominal dimensions, loads, materials, thresholds or equations in this refactor. The formatting-only phase separately compared every normalized manifest/module contract before and after. Connecting constants changes analysis contracts and therefore correctly invalidates old computational evidence. Requirement definitions and their reviewed baseline remain unchanged.

## Checks and remaining limits

The forced verification report `ec2b166c324d4a4c917a7ad453261687` reran all seven analyses and supports all 23 analytical obligations. Its contact audit checked 187 poses and found no rigid-part intersections. Comparing against the prior checkpoint confirmed the same 43 numerical outputs, 4 Boolean outputs, and ten part volumes and bounds, within numerical comparison tolerances. Length remains 140.5 mm, mass 18.20391 g, and peak button force 2.65746029 N. The existing reviewed requirement baseline is still current.

`tests/test_pen_connections.py` checks actual wrapper behavior when cam width and inactive spring turns change, verifies downstream impact, and checks that animation consumes its supplied rotational period. A scoped AST audit follows declared Python sources/imports and checks the wrappers' input-map reads against their declarations. This is useful for these wrappers; it does not prove all possible dynamic dependencies in arbitrary Python.

`tests/test_pen.py` builds the actual CAD, checks its solids and mass independently, verifies the analytical scope, and exercises the spring-wire change and restoration. The contact calculation samples native solids; it is not continuous collision proof or physical qualification. Three physical-test obligations remain open.

The verification record (development record) contains source line counts, preserved-model checks, output and geometry comparisons, passing Windows/Linux test results, the actual spring-change regression scope, GUI checks, package hashes and the protected-document hashes.

Mathematical coefficients, coordinate axes, topology counts, numerical epsilon constants, unit conversions, output rounding and visual styling remain in code where appropriate. For example, the Wahl correction's named coefficient is part of the chosen formula; RGB values and animation duration do not define engineering performance. Two equal tolerances are not automatically the same engineering decision.

The cam helper also retains standalone solver defaults; both production calls explicitly supply the recorded settings, including refinement. Those defaults do not independently determine a Closure run's resolution. This audit does not claim that every numeric literal has been removed.

The contact check's 0.001 mm³ tolerance and the motion check's click count are now visible settings, while the associated requirement prose still states their intended scope. Changing those settings needs an explicit engineering review of that claim; the current baseline guard does not understand the meaning of arbitrary prose or Boolean-producing scripts. This remains a modeling limitation, rather than a claim that every possible weakening is automatically detected.

For new projects, follow the [source authoring standard](AUTHORING_STANDARD.md): define design decisions once, explain assumptions, bind inputs by reference, export computed outputs and test meaningful cross-module changes.
