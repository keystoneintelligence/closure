# Closure source authoring

Closure source should let a reader follow a value from its definition to its consumers and the claims it supports. Use the existing YAML/JSON contract with concise formatting, stable names and explicit references. The format does not require a new expression language or an AI model to interpret it.

## Write each design value once

Define an independently chosen value in its owning module. Include units and a useful explanation; identify assumptions and their rationale. Export values that other modules consume. A computed value belongs in an analysis output. Consumers bind to the owning symbol instead of copying a number into another module or script.

```yaml
schema: closure/0.1
module: spring
owner: Spring engineering

parameters:
  wire: {value: 0.45, unit: mm}
  inactive_coils:
    value: 2
    description: Total closed end turns shared by calculations and CAD.

exports: [wire, inactive_coils]
```

A consuming analysis declares `wire: {ref: spring.wire, unit: mm}` under `inputs`. Its program reads the request input; it does not repeat `0.45`. The requested unit documents what the program expects and enables conversion. An output such as `force: {unit: N}` defines a quantity; `type: quantity` is redundant. Scalar, boolean, enum and artifact outputs retain their explicit type.

Design values, supplier assumptions and fit allowances belong in parameters. Sampling resolution, solver tolerances and meshing options belong in the analysis's `settings`; runners read `request["settings"]`, and those settings participate in evidence identity. Mathematical constants and unit conversions belong in the formula implementation, with comments where their meaning is not obvious. Viewer colors, explode distances and animation timing describe presentation rather than physical performance.

Equal numbers do not necessarily represent the same decision. For example, the spring's solid-height allowance and CAD end-turn pitch factor happen to equal 1.05 but have different meanings. Keep them separate. Conversely, derive a mating pocket from the key dimensions and its clearance instead of maintaining two independent copies of the geometry.

This is an authoring convention, not a blanket numeric-literal ban. Closure cannot prove that an arbitrary program declared every dependency. Review the wrapper and its imported helpers; use an input-change test to check important connections. State any uncontrolled external dependency explicitly.

## Default formatting

`closure format --project PATH` formats the manifest, referenced modules and Closure studies in `studies/`. `--check` reports files that need formatting without writing them, returning exit code 1 when changes are needed. The formatter leaves evidence, review records, report exports and simulator configuration files outside those selected source locations alone. Non-Closure files inside `studies/` cause a validation error instead of being rewritten.

The same formatter runs for `closure init` and parameter edits from the CLI or GUI. All bundled examples and templates use it. Existing projects can opt into the current style with one command; opening or checking a project does not silently rewrite its source.

- Short values, bindings and ports use compact mappings such as `{value: 12, unit: mm}` and `{ref: barrel.diameter}`.
- Short scalar lists stay inline; long interfaces use one entry per line.
- Descriptions and larger contracts remain readable block mappings, with blank lines between top-level sections.
- Empty optional fields and redundant types disappear only when omitting them produces exactly the same compiled contract.
- Meaningful empty strings, false values, zeros, explicit empty scopes and comments are preserved. JSON source remains JSON.

The formatter validates the result and compares the complete normalized contract before writing. It is idempotent. It preserves nonempty descriptions and rationales, even when they repeat, because they are distinct metadata fields. It does not change requirement limits, acceptance policy or baseline reviews.

## Verify a project

Press **Verify** in the viewer. Closure refreshes missing or stale analyses in dependency order, propagates their outputs, and reassesses the selected scenario and configuration. Independent branches can complete when another branch fails. The result is a saved evidence snapshot with failures, assumptions and unresolved obligations visible.

Select **Rerun all** before pressing Verify to execute every analysis in that context, including those with current evidence. This is useful when checking the complete execution chain. A failed rerun cannot use the old passing result to close the current verification. No requirement is relaxed automatically.

```sh
closure verify --project examples/pen --trusted
closure verify --project examples/pen --trusted --force
```

The Python equivalent is `Engine(project).verify(trusted=True, force=True)`. `build` remains compatible and accepts the same `--force` option. Verification runs authorized local programs and can take as long as those analyses require within their declared time limits. The button verifies the selected context; use a study to cover a set of configurations, scenarios or parameter combinations. It cannot replace the pen's still-open physical tests.
