# Preview compatibility

The candidate distribution supports standalone and composed projects. Each saved report retains the schema and digest it had when it was sealed.

| Product/boundary | Candidate | Commitment |
| --- | --- | --- |
| Core source contracts | `closure/0.2` | Standalone manifests, modules, ports and studies follow the [core specification](../spec/0.2/SPECIFICATION.md). |
| Composition manifest | `closure/0.2`, `preview.1` | Connects local projects through children, imports and exports using the [composition specification](../spec/0.2/COMPOSITION.md). |
| Runner exchange | `closure-run/0.2` | Standalone and composed projects share the typed stdin/stdout protocol. |
| Assessment reports | `closure-report/0.2` | Plans and saved reports use the format for their project. |
| Evidence and review | `closure-evidence/0.2`, `closure-review/0.2` | Both project formats preserve original records and their digests. |
| Python distribution / CLI | `closure-se==0.2.0a1` | Alpha; commands and JSON changes documented in changelog |
| Python import API | bundled reference backend | Provisional; pin the exact distribution |
| Viewer | `0.2.0-alpha.1`, bundled in the wheel | Install with matching backend; no separate npm release |
| Viewer HTTP API | `closure-viewer/0.2` | Local/provisional; negotiation required by the bundled client |

The candidate targets Python 3.10 and 3.12 on Windows and Linux. CI also tests Node 22 for building the viewer and the independent runner. Browser coverage is desktop Chromium and Firefox; other browsers, macOS, mobile and screen-reader support are not certified by this preview. See the release review for actual executed checks versus planned CI coverage.

Semantic identity is distinct from implementation version. Adding descriptions or clarifying a specification does not change its wire version. Changing defaults, reference resolution, unit meaning, acceptance, numeric identity or required fields incompatibly requires a new protocol identifier and migration guidance. Unknown protocol versions and unknown fields are rejected. Do not silently ignore extensions in safety-relevant records.

The current source and runtime schemas use `urn:closure:schema:0.2:<name>`. The release includes the schema files with both specifications. Pin the exact release archive and checksum while the specification is in preview. The changelog records changes that affect existing evidence.

## Upgrade a 0.1 project

1. Keep the authored files, reviews and `.closure` evidence directory together in an untouched copy. The candidate can inspect, explain and export sealed 0.1 reports by ID, including earlier composed reports that reference 0.1 evidence.
2. In the working copy, set the manifest, every module and every study to `schema: closure/0.2`. Add `kind: standalone` to a previously standalone manifest to keep local IDs such as `power.budget`. Existing unmarked 0.2 composition manifests retain qualified IDs.
3. Update each runner to accept `closure-run/0.2` and return that protocol and the request's invocation ID. Run `closure check`. A 0.1 source or runner requires migration before live verification can pass.
4. Retain 0.1 acceptance reviews outside the active review globs. Inspect the migrated obligations, use `closure approve-baseline` for each owner, and run `closure verify --trusted` to generate 0.2 evidence. Record any required acceptance decisions against the new evidence. Historical hashes and review decisions stay attached to their original records.

The 0.2 numeric digest profile retains the Python JSON encoding used for 0.1 evidence. Cross-language runners do not compute record hashes. Independent full evidence writers must reproduce the canonical profile and pass its vectors; this preview does not claim a second complete engine or RFC 8785 compatibility.
