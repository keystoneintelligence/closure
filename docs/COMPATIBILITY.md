# Preview compatibility

| Product/boundary | Candidate | Commitment |
| --- | --- | --- |
| Source specification | `closure/0.1`, `preview.1` | Explicit schema version; breaking meanings require a new version |
| Runner exchange | `closure-run/0.1` | Any language; strict typed stdin/stdout exchange |
| Evidence, report, review | `closure-evidence/0.1`, `closure-report/0.1`, `closure-review/0.1` | Preserve original objects and digests; no rewriting historical defaults |
| Python distribution / CLI | `closure-se==0.1.0a1` | Alpha; commands and JSON changes documented in changelog |
| Python import API | bundled reference backend | Provisional; pin the exact distribution |
| Viewer | `0.1.0-alpha.1`, bundled in the wheel | Install with matching backend; no separate npm release |
| Viewer HTTP API | `closure-viewer/0.1` | Local/provisional; negotiation required by the bundled client |

The candidate targets Python 3.10 and 3.12 on Windows and Linux. CI also tests Node 22 for building the viewer and the independent runner. Browser coverage is desktop Chromium and Firefox; other browsers, macOS, mobile and screen-reader support are not certified by this preview. See the release review for actual executed checks versus planned CI coverage.

Semantic identity is distinct from implementation version. Adding descriptions or clarifying a specification does not change its wire version. Changing defaults, reference resolution, unit meaning, acceptance, numeric identity or required fields incompatibly requires a new protocol identifier and migration guidance. Unknown protocol versions and unknown fields are rejected. Do not silently ignore extensions in safety-relevant records.

Versioned schemas use stable `urn:closure:schema:0.1:<name>` identifiers. These are identifiers, not network addresses. Publish the files alongside the specification under `spec/0.1/` and `schema/`; hosting domains can change without changing schema identity. Pin the exact release archive and checksum while the specification is in preview. A later candidate may clarify or fix behavior; the changelog must identify any effect on existing evidence.

No automatic migration is provided. Keep an untouched copy of authored sources and `.closure` before upgrading. Install the new wheel in a separate virtual environment, run `check` and `plan`, and review changed baselines before Verify. An engine, environment or source change can intentionally invalidate caches. Recompute evidence rather than editing old hashes. Export a saved report before archiving an old environment.

The 0.1 numeric digest profile follows Python's JSON serialization. Cross-language runners do not compute record hashes. Independent full evidence writers must reproduce the canonical profile and pass its vectors; this preview does not claim a second complete engine or RFC 8785 compatibility.
