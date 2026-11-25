# Preview compatibility

The candidate distribution supports standalone and composed projects. Each saved report retains the schema and digest it had when it was sealed.

| Product/boundary | Candidate | Commitment |
| --- | --- | --- |
| Core source contracts | `closure/0.1` | Standalone manifests, modules, ports and studies follow the [core specification](../spec/0.1/SPECIFICATION.md). |
| Composition manifest | `closure/0.2`, `preview.1` | Connects local projects through children, imports and exports using the [composition specification](../spec/0.2/COMPOSITION.md). |
| Runner exchange | `closure-run/0.1` | Standalone and composed projects share the typed stdin/stdout protocol. |
| Assessment reports | `closure-report/0.1` standalone, `closure-report/0.2` composed | Plans and saved reports use the format for their project. |
| Evidence and review | `closure-evidence/0.1`, `closure-review/0.1` | Both project formats preserve original records and their digests. |
| Python distribution / CLI | `closure-se==0.2.0a1` | Alpha; commands and JSON changes documented in changelog |
| Python import API | bundled reference backend | Provisional; pin the exact distribution |
| Viewer | `0.2.0-alpha.1`, bundled in the wheel | Install with matching backend; no separate npm release |
| Viewer HTTP API | `closure-viewer/0.2` | Local/provisional; negotiation required by the bundled client |

The candidate targets Python 3.10 and 3.12 on Windows and Linux. CI also tests Node 22 for building the viewer and the independent runner. Browser coverage is desktop Chromium and Firefox; other browsers, macOS, mobile and screen-reader support are not certified by this preview. See the release review for actual executed checks versus planned CI coverage.

Semantic identity is distinct from implementation version. Adding descriptions or clarifying a specification does not change its wire version. Changing defaults, reference resolution, unit meaning, acceptance, numeric identity or required fields incompatibly requires a new protocol identifier and migration guidance. Unknown protocol versions and unknown fields are rejected. Do not silently ignore extensions in safety-relevant records.

The core schemas use `urn:closure:schema:0.1:<name>`. The composition schemas use `urn:closure:schema:0.2:composed-project` and `urn:closure:schema:0.2:composed-report`. The release includes the schema files with both specifications. Pin the exact release archive and checksum while the specification is in preview. The changelog records changes that affect existing evidence.

No automatic migration is provided. Keep an untouched copy of authored sources and `.closure` before upgrading. Install the new wheel in a separate virtual environment, run `check` and `plan`, and review changed baselines before Verify. An engine, environment or source change can intentionally invalidate caches. Recompute evidence rather than editing old hashes. Export a saved report before archiving an old environment.

The 0.1 numeric digest profile follows Python's JSON serialization. Cross-language runners do not compute record hashes. Independent full evidence writers must reproduce the canonical profile and pass its vectors; this preview does not claim a second complete engine or RFC 8785 compatibility.
