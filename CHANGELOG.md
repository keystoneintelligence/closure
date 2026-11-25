# Changelog

## Unreleased

- The viewer can open sealed reports and run records after an invalid YAML edit, including on restart. CI exports the report from a verification with an open gate and keeps the job's failing status.
- A child can verify against a parent-owned constant with an unrelated sibling absent. Missing suppliers for calculated imports are reported with the declaring manifest, import alias and requested export. A child baseline that recorded unrelated suppliers needs one approval of the narrower contract.
- Composed gates count each applicable requirement once by its qualified ID, including when multiple child aliases lead to the same project. The viewer keeps each alias available for navigation.
- Requirement explanations in the CLI and viewer show the owning project's baseline status and reviewer. `explain REQUIREMENT --report ID` reads those details from the saved assessment.
- `plan --base` traces effective scenario and configuration override changes in each participating project to the analyses and requirements that consume those inputs.
- Plan and Verify schedule only the producers needed by scoped requirements in the selected scenario and configuration. Forced verification uses the same selection.
- An N/A review tracks the requirement's applicability declarations and context. Refreshing a shared producer preserves the review. When migrating from 0.1, record new applicability decisions against the 0.2 contexts.

## 0.2.0a1 local composition preview

- Link owned children and shared public values, artifacts and verified requirements across local projects.
- Assess the selected system, retain per-project gates and explain affected work in the CLI, viewer and exported history.
- Standalone and composed projects now share the 0.2 core, runner, report, review and evidence contracts. New standalone manifests specify `kind: standalone`. See the [migration steps](docs/COMPATIBILITY.md#upgrade-a-01-project) for live projects and runners. Sealed 0.1 evidence and earlier composed reports remain readable and exportable.


## 0.1.0a1 — early release candidate

The first coordinated release contains three separately described products: the Closure 0.1 specification, Python CLI/backend reference implementation, and bundled local browser viewer.

- Typed YAML/JSON projects connect authored inputs, analyses, requirements, contexts and evidence. Concise formatting omits redundant defaults while preserving model meaning.
- Verify selectively reruns affected analyses, propagates outputs, records immutable snapshots and explains unmet requirements. Force verification invalidates failed reruns safely.
- Human CLI output, progress, help examples, guarded parameter edits, JSON automation, history, completion and portable reports support everyday use.
- The general-purpose viewer edits inputs, verifies contexts, explains results and reopens saved evidence. Optional 3D artifacts come from project data.
- Preview contracts include versioned JSON Schemas, portable conformance fixtures and a JavaScript runner. Viewer/backend negotiation and keyboard dialogs are covered by release checks.

Source and runner identifiers remain `closure/0.1` and `closure-run/0.1`. Python import APIs and the viewer HTTP API are provisional. Historical 0.1 records retain their original hashes. This is an early interoperability preview, with trusted local execution and explicitly bounded conformance claims; see the specification and compatibility policy.
