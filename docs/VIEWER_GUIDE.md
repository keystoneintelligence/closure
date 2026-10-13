# Closure project viewer

The viewer runs on your computer and uses the same project loader, planner, runner, and assessment code as the CLI. It discovers projects inside an explicitly selected workspace and loads their contracts and current evidence.

```powershell
.\.venv\Scripts\closure.exe serve --project examples/service --workspace examples --trusted --port 8765
```

Visit `http://127.0.0.1:8765`. Omit `--trusted` to disable analysis execution from the browser. The server binds only to loopback; writes require its per-session token and a valid local origin. Stop it with Ctrl+C in the terminal that launched it.

**Overview** shows scoped closure, teams, evidence freshness, and exclusions. **System map** shows cross-team input and verification links. Select a team to inspect its supplied values, exported interface, and YAML contract. **Requirements** filters by team/status and explains each criterion, margin, assessment dimension, and causal path.

**Variables** lists authored inputs, assumptions, calculated outputs, and artifact references. Edit an authored value to see downstream impact; saving uses the source hash to reject conflicting edits and writes concise YAML/JSON. A reviewed limit edit opens baseline review. **Verify** refreshes affected analyses and reassesses requirements. Select **Rerun all** to execute every analysis in the selected context, even when its evidence is current. Restoring a previous input may reuse matching, intact evidence. A failed forced attempt withdraws the previous reusable result while preserving its history.

**Evidence** provides artifact downloads, immutable run provenance, source hashes, inputs, logs, and run history. **3D models** loads any produced GLB artifact. An optional `application/vnd.closure.assembly+json` artifact supplies named parts, ownership, colors, explode vectors, states, and optional motion keyframes. GLB coordinates use meters, while motion metadata currently uses millimeters. Model animation illustrates declared poses and does not prove mechanical behavior.

After a build, the viewer opens a **Historical build snapshot** with the saved model and assessments. **Evidence → Open snapshot** loads any verified saved build; **Inspect run** opens one analysis's recorded inputs, outputs, tool identities, source hashes, and logs. Historical views disable edits, builds, and context changes. Their source view shows the saved normalized contract rather than today's YAML. **Return to current project** restores the latest plan and editing controls. A historical passing gate does not make stale evidence current.

This distinction matters for external applications whose complete runtimes are not captured: the Blender/OpenFOAM example reruns them on each build and shows later plans as stale. Its completed build still remains inspectable and downloadable. Nonzero quantities below 0.0001 use scientific notation so small residuals do not appear to be zero.

The project selector loads another valid project under `--workspace`. Scenario and configuration selectors use that project's declared contexts, including names other than `nominal` and `default`. A project without geometry still supports team, requirement, variable, and evidence views.

## Portable reports

```powershell
.\.venv\Scripts\closure.exe export --project examples/service --output reports/service-review
```

Choose a new output folder. Export performs a read-only plan, copies only current artifact evidence, checks copied hashes, and publishes an HTML/JSON bundle. Open `index.html` without a server; `report.json` retains the assessment and run records, and `artifacts.json` maps output IDs to portable files. Stale historical artifacts are not exported as current evidence. A saved report is a dated snapshot; re-plan its source project to assess later changes.

Use `closure history --project PATH --json` to find saved report IDs, then `closure export --project PATH --report ID --output NEW_FOLDER` to export a historical build. This checks its report digest and artifact bytes without running analyses or requiring the current source to compile. The HTML labels the report as historical and includes its original time and context. A corrupt or missing artifact blocks the export instead of publishing an apparently complete bundle.

## Verification recorded during development

Browser checks exercised pen model loading, actuation, transparency, component selection, team interfaces, requirement explanations, the 0.45 → 0.55 → 0.45 mm spring regression, and loading/building the unrelated power project. HTTP tests additionally cover custom context names, origin/token checks, invalid bodies, source conflicts, path boundaries, and authored artifact downloads.

Pen assembly workspace (development record) · Pen failure explanation (development record) · Power project (development record)

## General-purpose project behavior

The overview uses requirement closure, module ownership and analysis freshness for every project. When no GLB evidence exists, it shows work needed to close the selected scope. It does not reserve a disabled assembly panel or require any mechanical data. Modules need not correspond one-to-one with teams.

Projects with GLB outputs get a 3D artifact selector. Assembly metadata must come from the same producing analysis and bind `model_output` to the selected output key (or fully qualified output ID). A plain GLB remains viewable and its named mesh components can be selected without metadata. Material, volume, CAD checks and manufacturing notes appear only when supplied. Other domains can provide a component `properties` mapping of text, numeric or boolean values.

GLB geometry uses meters and follows glTF's Y-up convention by default. Legacy `closure-assembly/0.1` metadata retains its documented Z-up behavior; an explicit `model_up_axis` of `x`, `y` or `z` selects another orientation. Motion fields with `_mm` and `_deg` suffixes explicitly use millimeters and degrees. Animation is a display of supplied data, not a viewer-side physics solver.

Optional `actuation.transitions` contains `{from, to, duration_ms, keyframes}` records. Each keyframe has normalized `t` and a `motions` list addressing named parts. Corresponding tracks interpolate translations, rotations and pivoted scale; any named state sequence is supported. Actuation and explosion controls appear only when their metadata is present.

Changing project or context hides the old assessment while new evidence is loaded. Builds and context selection cannot race through the controls. Saved builds remain explicitly historical and read-only.

Requirements can declare `all_of` criteria or `any_of` alternatives. The explanation shows each branch and the selected supporting alternative. One current passing alternative with evidence allowed by policy can close an `any_of` requirement even when another alternative is unavailable. A passing comparison with a disallowed evidence class still cannot close it. Required human reviews remain bound to the evidence and context.

`closure init --project PATH` starts with a small neutral contract and ordinary Python wrapper. Use `--template power` for the RFC's electrical example. Project folders may contain one of `project.yaml`, `project.yml` or `project.json`; ambiguous folders require an explicit manifest path. The GUI discovers canonical YAML and JSON projects inside its configured workspace. Parameter edits preserve JSON files as JSON.

The final browser pass exercised the service project at 390 px width and the four-module mission graph at 1280 px width, then restored the normal viewport. Both geometry-free examples use the same controls. The default preview is left on the service project. See the generic overview (development record), mission team map (development record), and objective audit (development record).

## Preview compatibility and accessibility

The bundled client negotiates `closure-viewer/0.1` with its backend and shows an explicit mismatch instead of operating against incompatible versions. Dialogs keep keyboard focus inside their controls; Escape closes them and returns focus to the invoking control. Chromium and Firefox browser tests exercise a real service-project edit, selective Verify, causal explanation and saved history. See [compatibility](COMPATIBILITY.md) and the [API contract](VIEWER_API.md). These checks do not constitute a complete accessibility certification.
