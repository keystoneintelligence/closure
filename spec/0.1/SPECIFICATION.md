# Closure 0.1

**Status:** public-preview specification, revision `preview.1`; reference implementation `0.1.0a1` (early release candidate). Published by Keystone Intelligence LLC under Apache-2.0.

Closure connects engineering claims to the inputs, computations and evidence that support them. Its central operation is **Verify**: resolve a selected context, determine which evidence is current, run the necessary analyses, propagate their outputs and assess the declared requirements.

This document specifies the implemented preview. “MUST”, “MUST NOT”, “SHOULD” and “MAY” describe requirements on the named conformance profile. A claim of conformance MUST identify a profile and this revision. Passing a software conformance suite does not validate the engineering model or physical system.

## 1. Products and conformance profiles

| Profile | Required behavior |
| --- | --- |
| Source reader | Parse supported source documents, apply defaults, resolve symbols and reject invalid graph/type/context relationships |
| Runner | Accept `closure-run/0.1` requests and produce matching, typed responses; no dependency on the reference implementation |
| Evidence reader | Validate original evidence/report shape, verify content identities using the canonical profile, preserve recorded context and distinguish historical from current support |
| Execution engine | Source-reader behavior plus dependency scheduling, freshness, runner validation, immutable evidence, requirement assessment and review rules |

The Python reference implements these profiles. The JavaScript example and independent AJV checks demonstrate runner exchange and structural schema interoperability. They are **not a second engine or a complete evidence-reader implementation**. Hash recomputation has a separate numeric compatibility obligation described in section 9.

The local viewer HTTP API and Python import API are implementation interfaces, documented separately. Closure 0.1 does not specify hosted execution, authentication, model exchange with SysML/ReqIF, optimization, a physics solver or a general systems-modeling metamodel.

## 2. Documents, versions and defaults

Authored documents are UTF-8 JSON or the JSON-compatible subset of YAML 1.2. Implementations MUST reject duplicate/non-string mapping keys, non-finite numbers, YAML tags, anchors, aliases and merge keys. The reference loader accepts a UTF-8 BOM, limits each source document to 2,000,000 bytes and nesting to 48 levels. Sources MUST have a mapping at the top level.

Every manifest, module and study declares `schema: closure/0.1`. Unknown versions and unknown contract fields MUST be rejected. Extensions need a new version or an external sidecar; arbitrary metadata cannot silently change the meaning of a 0.1 document. Application-specific strings are permitted where the schema declares a string map, such as semantic qualifiers or analysis settings.

The [nine JSON Schemas](../../schema/README.md) define field names, structural types, enums, required fields and defaults. Their `$id` is `urn:closure:schema:0.1:<name>` and their dialect is JSON Schema 2020-12. Schemas are normative for structure; the semantic rules here add checks that JSON Schema cannot express. Validators MUST NOT insert defaults into existing hashed runtime records.

| Document | Principal defaults when omitted |
| --- | --- |
| Manifest | `modules: [model/*.yaml]`; scenario `nominal`; configuration `default`; `scope: ['*']`; baseline `reviews/baseline.json`; reviews `reviews/acceptance/*.json` |
| Module | Empty parameters, analyses, requirements and exports; name/description empty; owner and module required |
| Datum | Type inferred; `origin: design`; rationale/description empty; no qualifiers or choices |
| Port | `type: quantity`, which requires a unit; no qualifiers or choices |
| Analysis | No inputs or validity predicates; `evidence_class: predicted`; `solver: false`; settings empty |
| Run | Timeout 120 seconds; stdout limit 2,000,000 bytes; no external tools, environment overrides or uncontrolled dependencies; stochastic false; seed null |
| Requirement | `applies_to: [nominal]`; `configurations: [default]`; required true; review_required false; method analysis; verification absent |
| Policy | Name concept; evidence classes assumed/predicted accepted; review and waivers disabled |

Omitting a requirement's context lists does not mean “all contexts.” A project using other context names MUST declare matching requirement applicability explicitly. Context sets and the effective required scope MUST be nonempty for a passing gate. Unbound requirements remain visible and cannot close.

The reference CLI discovers the nearest enclosing project directory. The source-reader profile begins at a selected manifest, without requiring that discovery behavior. A directory containing multiple `project.yaml`, `project.yml` or `project.json` files is ambiguous; select a manifest explicitly.

## 3. Symbols, graph and scope

Module identifiers and local parameter, analysis, output and requirement names match `[A-Za-z][A-Za-z0-9_-]*`. IDs are independent of filenames. A parameter is `module.parameter`; an analysis output is `module.analysis.output`; a requirement is `module.requirement`. Duplicate symbols or outputs MUST be rejected.

Bindings use full qualified IDs: `{ref: payload.peak_power}`. Cross-module consumers MUST reference an exported parameter or output. An export is a module-local parameter name or `analysis.output`. Unknown/private references and unknown exports are errors.

Analysis inputs and `valid_when` predicates establish computation dependencies. Requirements bind actual values and limits. `derived_from` records traceability to other requirements; it does not imply execution or automatically close a parent. The dependency graph MUST be acyclic. Feedback iterations belong inside one declared analysis/solver in this preview.

The graph includes `contains`, `consumes`, `produces`, `verifies` and `derived_from` edges. Module ownership, assessment acceptance and evidence support remain explicit associated fields.

`scope: ['*']` selects every requirement whose `required` field is true. An explicit scope lists qualified requirement IDs. Unknown IDs are errors. Requirements outside scope remain visible but do not determine the gate. A gate always describes one reported scenario/configuration/study point, not the whole design space.

## 4. Values, units and connected inputs

Supported types are quantity, scalar, boolean, string, enum and artifact. If `type` is omitted from an authored datum, inference is artifact when `path` is present, quantity when `unit` is present, boolean for a boolean value, string for a string value, otherwise scalar. Numeric values MUST be finite and MUST NOT be booleans. Enum values MUST belong to the declared nonempty `choices`. Artifacts use `path` and no scalar value.

Quantities MUST carry a unit. Other types MUST NOT carry a unit. The reference unit vocabulary is the default Pint registry in the supported dependency range. The portable fixture subset uses `W`, `kW`, `s`, `1/s`, `m`, `mm` and `percent`; additional units are accepted by the reference but independent implementations MUST declare their supported vocabulary and reject unsupported or dimensionally incompatible conversions. Units are case-sensitive. Quantities are converted into requested binding units or authored output-port units before comparison.

Qualifiers are exact string key/value semantics, for example `{frame: body}`. A binding's requested qualifiers MUST match the supplier's corresponding qualifiers. Runner output qualifiers MUST equal the declared port qualifiers. A criterion's actual and limit ports MUST have equal qualifiers.

Authored values SHOULD explain assumptions with `origin` and `rationale`. Analyses SHOULD consume shared values through declared inputs and export reusable results through outputs. Mathematical constants and local algorithm choices may remain in source/settings; engineering assumptions SHOULD NOT be repeated as unexplained literals. Closure tracks declared dependencies; it cannot infer every magic number, dynamic import or network dependency.

An artifact is opaque file content with SHA256 identity. Authored artifact paths and declared sources MUST remain inside the project root. Runners receive copied inputs in an execution snapshot; successful outputs are archived by content identity. A change in bytes invalidates consuming evidence. Artifact comparison belongs in a declared analysis that produces a scalar/boolean result; artifact paths are not numerical criteria.

## 5. Context and review-protected obligations

An execution engine resolves authored parameters, then configuration overrides, then scenario overrides, then study/ad hoc overrides; later layers win. An override MUST preserve type and qualifiers and use compatible units. If context selection is omitted, the reference selects the first declared scenario and configuration. Consumers needing deterministic selection across serializers SHOULD specify both names explicitly.

The reviewed obligation baseline covers requirement definitions, effective scope, scenario/configuration names, acceptance policy, parameters defining bound limits and relevant context overrides. Protecting limits includes recursively following analysis inputs that produce a limit. Study/ad hoc overrides MUST NOT alter protected limit inputs. Ordinary edits may propose such changes, but the gate MUST remain open until a separate baseline review approves the changed contract.

Review records carry reviewer, reason, time, context, decision and exact assessment hash. Valid decisions are accepted, rejected, waived and not_applicable. A changed assessment cannot reuse an unrelated review. These records are provenance, not authenticated signatures. Human identity and review independence require external access control and process.

## 6. Runner exchange

`run.argv` is an argument vector, never shell syntax. The reference treats `python`, `python3` and `{python}` as its current interpreter; other commands resolve on PATH. `sources` declares project-relative files/directories/globs to copy. Local statically resolvable Python imports are also captured; other languages and dynamic dependencies MUST declare required files explicitly. `environment_lock`, declared environment, executable tools and tool files contribute to provenance. Tool lookup may use local `CLOSURE_TOOL_<ALIAS>` configuration without changing the portable project.

The engine MUST send one JSON request on stdin with:

```json
{
  "protocol": "closure-run/0.1",
  "invocation_id": "0123456789abcdef0123456789abcdef",
  "context": {"scenario": "nominal", "configuration": "default", "point": "baseline"},
  "inputs": {"load": {"type": "quantity", "value": 80, "unit": "W", "qualifiers": {}}},
  "settings": {},
  "tools": {"executables": {}, "files": {}},
  "seed": null,
  "output_dir": "/engine-assigned/output"
}
```

A runner MUST emit exactly one JSON response on stdout and use stderr for diagnostics. It MUST echo the protocol and 32-character lowercase hexadecimal invocation ID. Its output names MUST exactly equal the authored output ports. Output envelopes may omit `type` where the port supplies it; quantity envelopes MUST still supply units. Artifact outputs name a file within the execution snapshot. The engine computes/verifies content hashes and normalizes scalar/quantity envelopes.

```json
{
  "protocol": "closure-run/0.1",
  "invocation_id": "0123456789abcdef0123456789abcdef",
  "outputs": {"total": {"value": 180, "unit": "W"}}
}
```

A solver MUST report `converged: true` for successful evidence and MAY report finite numeric residuals. A nonzero exit, timeout, oversized stdout, malformed/duplicate-key JSON, mismatched identity, undeclared output, invalid type/unit/qualifier, missing artifact, modified input/source snapshot or changed tool identity MUST prevent successful evidence publication. Downstream analyses without current inputs MUST be blocked. Unknown protocol fields MUST be rejected.

Reference execution requires explicit trust. Child-process lifetime cleanup does not create a security sandbox. Undeclared host files, shared libraries, services or remote runtime state may affect results. Such dependencies SHOULD be controlled or listed under `uncontrolled_dependencies`; known uncontrolled dependencies and unseeded stochastic analyses disable reuse.

## 7. Verify, freshness and propagation

Planning MUST NOT execute project programs. An engine computes execution identities from the analysis contract, declared/resolved dependencies, inputs, upstream evidence identities, execution environment/tools, context, settings and seed. The reference conservatively includes its own implementation sources and Python package environment. Cache-key construction and host-specific environment capture are reference implementation details; portability of cache hits across engines or machines is not promised.

Evidence is current only if the identity matches, required archived bytes pass integrity checks, reuse is permitted and upstream support is current. Missing means no usable evidence; stale means recorded evidence no longer supports the selected inputs/context. A previous successful value MUST NOT masquerade as current after its producing analysis fails.

Verify runs analyses in dependency order, reuses current permitted evidence and recomputes affected downstream analyses. `--force` reruns every analysis in the selected context. A failed forced run MUST invalidate the old reusable success for that execution identity. Successful records are sealed; each completed Verify saves a new assessment snapshot, including failures. The `executed` list identifies successful reruns; analysis state/error fields and progress events also describe failed attempts.

## 8. Requirement assessment and gates

A verification is a single criterion, a nonempty `all_of` list or a nonempty `any_of` list. Nested groups are unsupported. A criterion binds an actual value and a literal or bound limit, using `lte`, `gte`, `lt`, `gt`, `eq` or `ne`. Ordered comparisons require numbers. Quantities compare after converting the limit to actual units. Equality is exact; no implicit tolerance is added. Specify a tolerance as an explicit analysis/criterion if needed. Upper-bound margin is limit minus actual; lower-bound margin is actual minus limit; equality/inequality have no numerical margin.

Every assessment MUST preserve separate dimensions:

| Dimension | Values |
| --- | --- |
| Applicability | applicable, not_applicable |
| Freshness | current, stale, missing |
| Execution | complete, error, blocked, not_run |
| Verdict | pass, fail, unknown |
| Acceptance | accepted, rejected, review_required, waived, not_applicable |

`all_of` requires all branches. `any_of` uses a current passing branch, preferring one whose evidence classes are permitted by policy; an unused failing alternative does not veto valid support. Branch results remain visible. Authored design/assumption data count as assumed evidence; predicted/measured/established origins retain that class. Manual acceptance MUST NOT override rejected evidence classes.

A requirement is closed only when applicable, current, execution complete, verdict pass, acceptance accepted and the obligation baseline current. Review-required policies/requirements need a matching acceptance record. A policy-authorized waiver can allow the gate while leaving the requirement visibly unverified. A non-applicable scoped requirement requires an explicit matching not_applicable review to be excluded. The gate is true only for nonempty valid scope/contexts, a current baseline and every scoped requirement permitting the gate.

Studies use either a nonempty parameter grid or explicit points, exclusively, across declared scenario/configuration selections. Every requested outcome MUST remain in the aggregate, including failed or missing evidence. A sampled study makes no claim about unsampled behavior.

## 9. Evidence, canonical identity and history

Evidence records use `closure-evidence/0.1`; reports use `closure-report/0.1`; reviews use `closure-review/0.1`; study results use `closure-study/0.1`. Runtime schemas define their full shape. Saved reports include the normalized model and context, enabling historical inspection after source changes. A plan lacks a report digest. A saved report MUST include one.

Digests are lowercase SHA256 over canonical UTF-8 JSON bytes. For an evidence record exclude only its top-level `record_hash`; for a report exclude only its top-level `report_hash`. Artifact digests hash raw file bytes. Do not normalize Unicode, change numeric types, add defaults or reserialize historical objects with an incompatible encoder before validation.

The **0.1 reference numeric profile** is `json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)` under supported CPython. Objects sort keys by Unicode code point; arrays retain order; strings use JSON escapes for quotes, backslashes and control characters, with non-ASCII Unicode encoded directly; no insignificant whitespace or byte-order mark is added. Booleans/null use lowercase JSON literals. Integers use base-10 digits without a decimal point. Binary64 floats use CPython's shortest round-trippable decimal representation, preserve a floating `.0` where emitted, use lowercase `e`, an explicit exponent sign and at least two exponent digits. `1`, `1.0` and `-0.0` are distinct canonical numbers. Non-finite values and unpaired surrogate strings have no valid canonical UTF-8 representation.

This is **not RFC 8785**. A client using JavaScript's ordinary `JSON.parse`/`JSON.stringify` loses integer-versus-float lexical distinctions and MUST NOT claim verified record hashes from that round trip. Runners can consume recorded identities without recomputing them. Independent evidence writers/readers must implement this profile or preserve canonical tokens and verify the supplied [vectors](../../conformance/README.md). Improving numeric portability is an explicit subject for a future protocol revision, not a silent 0.1 change.

Historical objects MUST be structurally validated before use and their hashes and referenced artifact bytes verified when opening/exporting a snapshot. New records archive consumed input files using `inputs_archived: true`; older records without the flag retain their original interpretation and may depend on original input files. Missing new optional diagnostic fields must not rewrite historical bytes. Hashes detect corruption; they do not prove authorship or truthful execution.

## 10. Diagnostics and conformance checks

Errors are explicit, with a machine-readable `code`, human `message` and optional source `location`. Representative codes include SCHEMA, UNKNOWN_REF, PRIVATE_REF, INVALID_ID, COMPUTE_CYCLE, UNIT_MISMATCH, QUALIFIER_MISMATCH, UNKNOWN_CONTEXT, TRUST_REQUIRED, OUTPUT_INVALID, BLOCKED, INVALID_DOMAIN, OBLIGATION_CHANGE and integrity errors. Human wording and paths are not stable identifiers. The CLI uses exit 0 for success, 1 for an open assessment gate, 2 for invalid input/setup, and 130 for interruption.

The [conformance package](../../conformance/README.md) provides valid/invalid structural vectors, canonical bytes/digests and a JavaScript runner project. The engine regression suite adds semantic tests for linking, cycles, units, output identity, acceptance, freshness, corruption, forced execution, source edits and historical integrity. Conformance claims MUST list the cases and profiles actually exercised. New implementations SHOULD also wrap an existing analysis in another domain and demonstrate that a changed input produces a causal, inspectable failed requirement.

## 11. Version evolution

Breaking source defaults, value meanings, references, exchange shapes, acceptance rules or canonical identities requires a new explicit version and migration guidance. Unknown versions are errors; do not guess compatibility. Preserve old evidence with its original version. The implementation version, specification revision and viewer version advance separately and are coordinated in [compatibility policy](../../docs/COMPATIBILITY.md).

Before a stable specification, the project seeks feedback on non-Python evidence interoperability, unit vocabulary, extensions, realistic toolchain dependency capture and first-session onboarding. This preview exposes a usable contract and its present limits for that review.
