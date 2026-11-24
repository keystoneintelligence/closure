# Local project composition

The `closure/0.2` manifest composes local projects. Modules, ports and runner requests use the 0.1 contracts. Existing 0.1 manifests continue to select single projects. The new manifest and report schemas are [composed-project](../../schema/composed-project.schema.json) and [composed-report](../../schema/composed-report.schema.json).

## Author a root

```yaml
schema: closure/0.2
project: system
children:
  cooling: {path: cooling}
imports:
  demand: {path: cooling, export: power}
```

A child participates in system acceptance by default. Set `required: false` to record an exclusion. An import identifies a public symbol from a supplier. Declare `exports: {power: load.scale.demand}` in the supplier and use `{ref: "@demand", unit: W}` in a consumer module. Project exports may name local parameters, analysis outputs (including artifacts), or requirements. To depend on a verified requirement, import its export and include the alias in the consumer manifest's `required_claims` list. Closure evaluates the actual requirement and retains its evidence and policy. A numerical system requirement still needs its own verification rule.

Paths are relative to the declaring manifest. A link accepts a directory, manifest file, or local file URL. An empty `.closure-workspace` file marks an explicit workspace root. Otherwise the enclosing Git worktree establishes the boundary, or the selected directory when neither exists. The viewer also enforces its configured workspace. Project IDs must be unique. Links to the same resolved source share its instance. A qualified report ID looks like `cooling::load.scale`. Module-local references retain their original spelling.

The initial preview uses matching scenario and configuration names across participants. Each project resolves its own configuration overrides, then scenario overrides. Explicit study overrides apply last. Separate contexts have separate execution keys. A missing context or incompatible unit blocks assessment.

## Verify and inspect

The planner orders producers by their actual inputs. A child can supply design data before its own requirements close. Checking a component independently follows its imports and selects its required descendants. A shared supplier contributes only the imported evidence unless the manifest also declares ownership. Ordinary computational cycles and containment cycles produce diagnostics.

A required project closes when its selected requirements, explicit claim imports and required children satisfy their policies. Baselines cover scoped acceptance definitions. Required children retain their own baseline authority. Evidence classes and waiver permissions must satisfy the responsible projects, and any required review still applies. Each required subtree must have at least one applicable obligation. See the [worked power example](../../examples/composed-power/README.md).

Each project gate counts distinct applicable requirements by qualified ID across its scope, required claims and required descendants. A shared child's requirement contributes once to each parent's count and once to their common ancestor's count. The viewer preserves every alias leading to a required child.

Composed reports record each evaluated project's baseline assessment in `project_baselines`, keyed by project ID. The top-level `baseline` describes the selected assembly. A requirement explanation uses the defining project's entry, including its reviewer when available. Historical explanations read the sealed report. An earlier report's project gate can establish a baseline status. Reviewer attribution requires the captured baseline.

For a calculated limit, the baseline includes the producing analyses, their settings, declared code and files, upstream input values, validity conditions, and the contents of input artifacts. Changing the formula can require review even when the numerical limit stays the same. Earlier baselines that omitted a calculation require one new approval. A change confined to the measured or predicted result refreshes its evidence under the existing criterion.

The same analysis uses its defining project's active evidence store when verified independently or through an assembly. The assembly checks the execution key, context and record integrity before linking that exact run. A forced run produces fresh evidence and requires its own review where policy calls for one. Each verification archives the linked records and artifact bytes alongside its selected project's report for offline inspection. For read-only suppliers, new work is cached in the writable selected project.

To resume verification in another checkout, restore the participating projects' active evidence stores along with their review files. Historical reports and exported bundles remain independently readable. A parent evaluates its own acceptance policy when linking a child review. A stricter evidence policy, a different verification alternative, or a rejection that its reviewer has kept in effect can keep the assembly open.

An assessment records the project hierarchy, imports, exclusions, scopes, reasons for open gates, execution decisions, source revision when available, and comparisons. The saved report retains its normalized source model and references to verified evidence. Keep the selected project's `.closure` evidence directory with CI artifacts, or export a portable report. Comparing saved reports requires their original records. A checksum verifies file identity; a change explanation identifies the requirement, owner, quantity, unit, and affected work.

CI should check out the exact candidate revision, run `closure check` and `closure verify --trusted` on the root, and retain its report and evidence even if validation fails. Restrict trusted execution to code and tools the project owner has reviewed.
