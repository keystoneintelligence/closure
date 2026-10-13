# Closure source and runner guide

## Project structure

A project has `project.yaml`, one or more module documents, optional studies, ordinary analysis programs, and review records. The `schema` value is `closure/0.1`. See `examples/power/` for a complete executable example and `schema/` for the generated contract definitions.

The loader accepts the JSON-compatible subset of YAML 1.2. It rejects duplicate or non-string keys, YAML tags, aliases, anchors, merge keys, non-finite numbers, unknown contract fields, excessive depth, and documents over 2 MB. Source locations appear in linking and cycle diagnostics.

Module identifiers and local element names form stable qualified IDs. Cross-module inputs must be exported explicitly. Computation edges are derived from analysis input references; requirements can reference produced outputs or authored data. Traceability and parent links do not imply execution order or parent verification.

## Values and files

Supported data types are quantities, scalars, booleans, strings, enums, and opaque artifacts. Quantities carry units, converted through Pint. Semantic qualifiers such as frame or aggregation can be declared on ports and bindings; incompatible declared qualifiers are rejected.

An authored artifact is a project-relative file:

```yaml
parameters:
  design:
    type: artifact
    path: assets/assembly.step
exports: [design]
```

Another team can consume `{ref: supplier.design}`. The runner receives an immutable input identity and a copied file in its execution directory. Changing file content invalidates dependent evidence. A directory-based simulation case belongs in an analysis's declared `sources`; its files are snapshotted together. This mechanism is format-neutral and does not imply that a particular external application has been installed or run.

## Runner protocol

`run.argv` is an argument list, never a shell command. The tokens `python`, `python3`, and `{python}` select Closure's current Python interpreter. Other executables resolve through the local PATH. `run.sources` contains project-relative files, directories, or globs. Statically resolvable local Python imports are included transitively; dynamic imports and external services require explicit dependency declarations.

Executable paths retain their invocation location, including virtual-environment symlinks. Following those symlinks before launching Python can select the base environment and lose installed packages. The executable bytes are still hashed; the actual invocation path is retained in provenance.

Closure copies declared sources and artifacts into a temporary execution directory and sends a JSON request on stdin:

```json
{
  "protocol": "closure-run/0.1",
  "invocation_id": "engine-assigned-id",
  "context": {"scenario": "nominal", "configuration": "default", "point": "baseline"},
  "inputs": {"load": {"type": "quantity", "value": 80, "unit": "W", "qualifiers": {}}},
  "settings": {},
  "tools": {"executables": {}, "files": {}},
  "seed": null,
  "output_dir": "absolute-temporary-output-directory"
}
```

The program writes one JSON response on stdout and diagnostics on stderr:

```json
{
  "protocol": "closure-run/0.1",
  "invocation_id": "engine-assigned-id",
  "outputs": {"total": {"value": 180, "unit": "W"}}
}
```

Output names must exactly match the contract. Artifact outputs return `{ "path": "outputs/model.step" }`; absolute paths inside the execution snapshot also work. Closure computes the digest and stores the bytes. A solver analysis additionally returns `converged: true` and can include residuals.

Exit failures, malformed output, duplicate JSON keys, wrong invocation IDs, incompatible values, missing output files, source snapshot modification, timeouts, or output limits prevent publication. Successful records are immutable JSON documents under `.closure/runs/`; artifact bytes are addressed by SHA256 under `.closure/artifacts/`. Corrupt stored artifacts are preserved in quarantine when a rebuild restores them.

The [published contracts](../schema/README.md) cover runner requests/responses, sealed evidence, reports, study results and review records as well as source documents. They are generated from the models used to validate these boundaries. JSON Schema checks structure; the engine additionally checks the exchange against its invocation and authored ports. Artifact types and qualifiers are checked as strictly as scalar and quantity results.

Local process cleanup runs after successful completion, failure, a time/output limit, or an interrupted build. Windows execution assigns the suspended wrapper to a [Job Object](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects) before starting it, then terminates remaining members and waits for resource release. POSIX execution uses a separate process group. Wrappers should wait for their own tools before returning their response. These controls cover ordinary local descendants; deliberately detached POSIX daemons, WSL guest processes and remote services require adapter-specific cancellation. They do not provide a security sandbox or impose limits on artifact disk size, memory or CPU use.

## Evidence and review

Execution identity includes the analysis contract, source/dependency snapshot, executable identity, resolved Python environment, inputs, upstream record identities, context, settings, and seed. The engine also fingerprints its own source during development. A moved module file retains its symbols; an unrelated parameter edit does not change an analysis's identity.

Known uncontrolled dependencies and unseeded stochastic analyses disable cache reuse. The executor runs trusted code on the host. It is not a security sandbox or a guarantee that undeclared files, dynamically loaded tools, or network services cannot affect a result.

Declare external executables under `run.tools`, for example `{blender: blender}`. A local `CLOSURE_TOOL_BLENDER` environment variable can supply an absolute executable path without changing the portable contract. Closure resolves the executable and hashes its bytes during planning; it does not execute a version probe. The runner request and evidence record expose `tools.executables.<alias>.path` and `.sha256`. `run.tool_files` can identify additional runtime files, relative to the project root or by absolute path. Missing tools produce explicit diagnostics, and tools or declared runtime files that change during execution prevent publication.

Executable hashes alone do not capture shared libraries, plugins, remote runtimes, or external services. Declare those limitations under `run.uncontrolled_dependencies` unless their relevant state is controlled. The [Blender and OpenFOAM example](../examples/multitool/README.md) demonstrates real execution with conservative cache behavior.

The reviewed baseline records requirement definitions, scope, scenario/configuration names, policy, and inputs that define bound requirement limits. Changes require a separate explicit baseline review. Study overrides cannot weaken bound limits. Review records identify the reviewer, reason, decision, context, and exact assessment hash. These are provenance records; repository permissions and independent human review provide access control.

Freshness, execution, numerical verdict, applicability, and acceptance remain distinct. A waiver can permit a gate only when policy allows it, and remains visibly unverified. A manual acceptance cannot override the policy's allowed evidence classes. Out-of-scope and not-applicable obligations remain visible; not-applicable gate exclusions require an explicit matching review.

`build` assesses one selected configuration/scenario. Its gate applies only to that reported context. `sweep` executes every requested point and retains failures and missing evidence in its totals. Parameter sweeps do not prove unsampled behavior.

## Guarded changes

`closure patch --expected-hash HASH --changes JSON` updates authored parameters while preserving YAML comments. It rejects a patch prepared against an earlier source hash. Builds and parameter edits use a project write lock. After a terminated writer, establish that its process has ended before removing an abandoned `.closure/write.lock`.

`plan --base REF` compiles the committed Git project and compares parameter, analysis, and requirement contracts with the working tree. It reports moved modules, changed declared/transitive sources, artifact content changes, affected analyses and requirements, context changes, and obligation changes. A prose-only requirement edit can require review without a numerical rerun. Git text normalization is respected so Windows line endings do not make every unchanged source appear modified.

The comparison reads a bounded archive of the project subtree, rejects links/special files, and executes no analysis code. The committed baseline must compile and contain its declared sources. Git `export-ignore` attributes can omit files from that archive; such a baseline must be made complete before comparison. The source comparison reports potential impact; the current evidence plan and separately reviewed obligation baseline determine the gate. Git is optional for all other operations.

## Viewer and report export

`closure serve --workspace PATH` exposes the local viewer; `--trusted` enables builds. `closure export --output NEW_FOLDER` writes a portable HTML/JSON evidence bundle with verified copies of current artifacts. Neither planning nor export executes analysis code. See the [viewer guide](VIEWER_GUIDE.md) for project selection, edits, model interaction, and report contents.

Every completed build now saves its normalized source model, graph, assessments, and referenced run records with a `report_hash`. `closure history` lists saved builds and individual runs. `history --report ID` and `history --run ID` inspect their original evidence; `export --report ID --output NEW_FOLDER` exports a historical build without compiling or running the current source. This remains useful after source edits, missing tools, or a project move. Artifacts resolve by content address within the selected evidence store, never by a historical absolute path.

Historical inspection verifies the report/record digests and output artifact bytes. History listings check record digests; opening a snapshot additionally checks artifacts. These hashes detect accidental modification and corruption; they are not cryptographic signatures or authorization controls. Legacy reports without a saved model and report digest cannot be opened as verified full snapshots, but their valid individual run records remain inspectable. A historical passing gate always describes its saved design, context, and policy.

New run records also archive consumed input files and mark them with `inputs_archived: true`. Their integrity checks include those input bytes, and portable exports include them with `role: input` in the artifact manifest. A program that modifies its copied input cannot publish evidence. Legacy records without this flag retain their original input digests, but may require the original source files to inspect those inputs.

## Version 0.1 model and interoperability boundaries

The persisted model includes module ownership, typed values and producer bindings, contexts, verification criteria, and evidence/review records. The exported dependency graph currently exposes `contains`, `consumes`, `produces`, `verifies` and `derived_from` edges. Ownership and evidence support/acceptance are represented in the associated module, assessment and record fields rather than additional free-form graph edges. Arbitrary `allocated_to` relations and a general systems-modeling metamodel are unsupported.

Stable IDs survive file moves. Renaming a namespace requires an explicit source migration updating its references and exports; there is no automated rename/migration command. Source and runner versions are `closure/0.1` and `closure-run/0.1`; schema changes must preserve these contracts or introduce a new version. Diagnostic codes are machine-readable and covered by conformance tests, with filenames/locations where available.

There is no SysML v2 or ReqIF import/export adapter in this release. Their supported conversion subset is therefore empty: behavior/state-machine semantics, arbitrary allocations, inheritance, variation models and lossless document exchange are not supported. Existing tools integrate through typed JSON runners and file artifacts. The project does not claim a full SysML implementation, distributed execution, authenticated review signatures, a security sandbox, optimization, or formal verification of physical models.
