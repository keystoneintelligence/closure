# Closure 0.2 core specification

This is revision `preview.1` of the Closure 0.2 specification. The reference implementation is the `0.2.0a1` early release candidate, published as source by Keystone Intelligence LLC under Apache-2.0.

Closure connects a requirement to its inputs, the analyses that produce its evidence, and the policy used to assess it. Verify answers whether the declared requirements close for one scenario, configuration and study point. A saved assessment records which evidence supported that answer.

## Conformance

A conformance claim MUST name the specification revision and the profiles it implements. A **source reader** validates source documents, resolves references and checks the resulting graph, types, units and contexts. A **runner** implements the JSON exchange described below. An **evidence reader** validates records and their content identities. An **execution engine** implements the source-reader behavior, schedules analyses, checks freshness, assesses requirements and seals the resulting evidence.

The [JSON Schemas](../../schema/README.md) specify required fields, types, allowed values and defaults. They use JSON Schema 2020-12 and identifiers of the form `urn:closure:schema:0.2:<name>`. The rules below also apply to relationships across documents. The [composition specification](COMPOSITION.md) defines the additional linking, ownership and acceptance rules for composed projects. The [compatibility policy](../../docs/COMPATIBILITY.md) identifies the Python distribution and viewer interfaces.

## Source documents

Manifest, module and study documents MUST declare `schema: closure/0.2`. A standalone project MUST declare `kind: standalone` on its manifest. A 0.2 manifest without that field uses the composition profile, including when it has no children. This preserves the meaning of existing composition manifests. A standalone requirement can have the ID `budget.power`. The same local requirement in a composed project named `system` has the ID `system::budget.power`.

```yaml
schema: closure/0.2
kind: standalone
project: power
modules: [model/*.yaml]
```

Source is UTF-8 JSON or the JSON-compatible subset of YAML 1.2. The top level MUST be a mapping. A reader MUST reject unknown versions and fields, duplicate or non-string keys, merge keys, YAML tags, anchors and aliases, and non-finite numbers. The reference accepts a UTF-8 BOM, limits source documents to 2,000,000 bytes and limits nesting to 48 levels. A directory with several of `project.yaml`, `project.yml` and `project.json` requires an explicit manifest selection.

The manifest defaults to `model/*.yaml`, scenario `nominal`, configuration `default` and scope `['*']`. A module declares its ID and owner. Module IDs and local symbol names match `[A-Za-z][A-Za-z0-9_-]*`. References identify symbols independently of filenames. A parameter is named `module.parameter`, an output `module.analysis.output` and a requirement `module.requirement`. Cross-module value references MUST resolve to exported parameters or outputs. Unknown, private and duplicate symbols are errors. Cross-project references use the [composition rules](COMPOSITION.md).

Analysis inputs and validity predicates depend on their referenced values. A requirement's criteria bind actual values and limits. The resulting computation graph MUST be acyclic. A `derived_from` reference records traceability between requirements. A parent requirement needs its own acceptance definition to close.

## Values and interfaces

Supported types are quantity, scalar, boolean, string, enum and artifact. With an omitted type, an artifact path implies an artifact, a unit implies a quantity, a boolean implies boolean, and a string implies string. Other numeric data default to scalar. Numeric values MUST be finite and booleans cannot serve as numbers. An enum declares its choices and its value MUST be a member. An artifact declares a path without a scalar value.

Quantities require a unit. A consumer can request a compatible unit on a binding. The engine MUST convert quantities before comparing values and reject dimensionally incompatible units. Units are case-sensitive. The reference uses Pint. Independent implementations SHOULD identify the unit vocabulary they support. Each qualifier requested by a consumer MUST match the supplier. Output qualifiers MUST equal the declared port qualifiers. The two sides of a comparison MUST have matching qualifiers.

Authored data can declare an origin, rationale and description. A requirement that compares design or assumption data uses the assumed evidence class. Analyses declare an evidence class, defaulting to predicted. Artifacts are opaque bytes identified by SHA256. An authored artifact or analysis source must resolve inside its source project. A runner receives a copy of its input artifacts. The engine verifies and archives produced artifact bytes.

## Context, planning and execution

The effective parameter values come from authored values, configuration overrides, scenario overrides and finally study or ad hoc overrides, in that order. Overrides MUST preserve type and qualifiers and use compatible units. In the absence of a selection the reference chooses the first declared scenario and configuration. A study chooses either a grid of nonempty axes or explicit points. It MUST retain outcomes for every requested point, including failed and missing results.

Wildcard scope selects the project's required requirements. An explicit scope selects the named requirements. A requirement applies when its `applies_to` list contains the selected scenario and its `configurations` list contains the selected configuration. The default lists contain only `nominal` and `default`, respectively.

Plan and Verify MUST use the same context-specific work list. Starting at applicable scoped requirements, the engine follows actual and limit bindings, analysis inputs and validity conditions to their producers. It includes each producer once, in dependency order. Planning MUST NOT execute project programs. A non-applicable requirement can still need an applicability review. Its exclusive dependencies do not run.

Verify can reuse evidence only when its execution identity matches, its recorded dependencies and required archived artifacts pass validation, and its reuse policy permits it. The reference identity includes the analysis contract, context, inputs, upstream record identities, declared source and tools, and execution environment. Known uncontrolled dependencies and unseeded stochastic runs disable reuse. A failed forced refresh MUST withdraw the previous reusable success for that execution identity. The report identifies successful reruns in `executed` and exposes failed or blocked analyses separately.

## Runner exchange

The engine invokes the declared argument vector `run.argv` in a snapshot of the declared sources. The reference resolves `python`, `python3` and `{python}` to its own interpreter. Declare source files, environment locks, tools and tool files that affect execution. The reference captures local Python imports that it can resolve statically. Record uncontrolled external inputs or services explicitly. Execution requires trust in the programs and tools involved.

The engine MUST send one [runner request](../../schema/runner-request.schema.json) as JSON on stdin. It declares `protocol: closure-run/0.2`, a fresh 32-character lowercase hexadecimal invocation ID, the selected context, typed input values, settings, tools, a seed or null, and an output directory.

```json
{
  "protocol": "closure-run/0.2",
  "invocation_id": "0123456789abcdef0123456789abcdef",
  "context": {"scenario": "nominal", "configuration": "default", "point": "baseline"},
  "inputs": {"load": {"type": "quantity", "value": 80, "unit": "W", "qualifiers": {}}},
  "settings": {},
  "tools": {"executables": {}, "files": {}},
  "seed": null,
  "output_dir": "/engine-assigned/output"
}
```

A runner MUST emit one [runner response](../../schema/runner-response.schema.json) on stdout and write diagnostics to stderr. The response MUST echo the protocol and invocation ID. Its output names MUST match the declared ports exactly. Each output envelope MUST satisfy its port. A runner can omit an output type when the port supplies it. Quantity outputs still require units. Artifact outputs must identify a file within the execution snapshot.

```json
{
  "protocol": "closure-run/0.2",
  "invocation_id": "0123456789abcdef0123456789abcdef",
  "outputs": {"total": {"value": 180, "unit": "W"}}
}
```

A solver MUST return `converged: true` and MAY include finite numeric residuals. A nonzero exit, timeout, excessive output, malformed or duplicate-key JSON, unknown fields, mismatched invocation or protocol, invalid port output or changed declared input MUST prevent publication of a successful run. Analyses that require the missing evidence remain blocked. The reference defaults to 120 seconds and 2,000,000 bytes of output.

## Assessment and reviews

A requirement declares one criterion or one nonempty `all_of` or `any_of` group. A criterion compares a bound actual value with a literal or bound limit. Operators are `lt`, `lte`, `gt`, `gte`, `eq` and `ne`. Ordering requires numbers. Equality uses the compared values after any required unit conversion. Define a tolerance explicitly when the engineering criterion calls for one. The upper-bound margin is limit minus actual. The lower-bound margin is actual minus limit.

An assessment MUST distinguish applicability, evidence freshness, execution, verdict and acceptance. A missing or stale result cannot establish a current pass. Every `all_of` branch must pass. An `any_of` group needs a current passing branch and prefers support allowed by the evidence policy. The branch diagnostics preserve the alternatives and record the support selected.

The reviewed obligation baseline uses `closure-baseline/0.2` and covers the requirement definitions, scope, contexts, acceptance policy and protected limits. A derived limit includes the analyses, source and declared files, settings, upstream values and validity conditions used to calculate it. A changed obligation requires a new baseline approval. Study and ad hoc overrides MUST NOT change protected limit inputs.

Acceptance reviews identify the requirement, reviewer, reason, decision, time, context and assessment identity. An applicable requirement closes when its evidence is current, execution is complete, its verdict passes, its baseline is current and its policy admits the evidence and the acceptance decision. A review cannot make a disallowed evidence class acceptable. A waiver can permit the gate only when allowed by policy. A scoped non-applicable requirement needs an explicit matching `not_applicable` review to be excluded. Its review binds the requirement identity, declared applicability sets and selected context, so refreshing a shared producer preserves that review.

A gate applies to its reported context. It requires nonempty valid scope and contexts, a current baseline and a permitting assessment for each scoped requirement. Composed gates also include required children and claims, use each defining project's baseline and count distinct applicable obligations across the required subtree. A second alias for a child preserves the authored relationship while counting the same qualified requirement once.

## Sealed evidence and historical inspection

Current successful runs use `closure-evidence/0.2`, reviews use `closure-review/0.2`, reports use `closure-report/0.2` and study results use `closure-study/0.2`. Both report profiles share a version tag. The [standalone report](../../schema/report.schema.json) includes a `kind: standalone` model manifest. The [composed report](../../schema/composed-report.schema.json) includes the composition model and project gates. A saved report includes a snapshot of the model and its context. A plan has no report digest. Each completed verification seals an assessment, including an open gate.

A record hash covers the record except its top-level `record_hash`. A report hash covers the report except its top-level `report_hash`. Digests are lowercase SHA256. For records and reports the input bytes are canonical UTF-8 JSON. For an artifact the input is the exact file content.

The reference canonical numeric profile uses CPython's `json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)`. Objects sort by Unicode code point. Arrays preserve element order. The encoder emits no insignificant whitespace or byte-order mark. Booleans and null use lowercase JSON literals. Integers use decimal digits. Binary64 values follow CPython's shortest round-trippable representation, preserving a float's decimal point or exponent where emitted. Exponents use lowercase `e`, an explicit sign and at least two digits. The encodings of `1`, `1.0` and `-0.0` are distinct. Non-finite numbers and unpaired surrogates have no valid encoding.

A reader MUST validate the original object before using it. It MUST verify its digest and the required archived artifact bytes when opening or exporting a saved assessment. Defaults, type conversions or a serializer that collapses integer and floating-point representations can change a digest. Implementations that recompute identities MUST preserve the canonical values and pass the [conformance vectors](../../conformance/README.md). Runners can use the supplied identities directly.

The reference can inspect a sealed report, its original normalized model, explanation, runs and archived bytes when live source is unavailable. Historical reads MUST preserve original bytes, version tags and digests. Older input artifacts that were never archived may require the original files. Earlier reports can lack owner baseline details or branch diagnostics. A reader MUST NOT invent missing historical evidence.

## Migration and diagnostics

The 0.2 execution profile requires migration for live projects. Keep the original source and evidence store. For a standalone 0.1 project, set the manifest to `closure/0.2` with `kind: standalone` to preserve local identifiers. Update each module and study to `closure/0.2`. For an earlier unmarked 0.2 composition, keep the composition manifest unmarked and migrate its reachable source documents. Update runners to accept and echo `closure-run/0.2`.

Retain earlier acceptance reviews outside the active review-file patterns. Review each owner's migrated obligations and approve its 0.2 baseline. Verify to produce current evidence and record any acceptance decisions the policy requires. Preserve prior sealed records and reports in their original formats. This includes earlier composed reports with a 0.2 outer tag and embedded 0.1 contracts.

The CLI returns exit status 0 on success, 1 for an open gate, 2 for input or setup errors, and 130 for interruption. A diagnostic includes a stable machine-readable code and explanatory text, with a source location where available. Conformance claims SHOULD identify the tested cases, including malformed inputs, incompatible bindings, failed executions, changed evidence and historical validation.
