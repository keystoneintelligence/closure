# Local viewer API: closure-viewer/0.2

This provisional API is bundled with `closure-se==0.2.0a1`. Use the matching viewer assets. It serves one selected project per local server session; project selection affects all tabs. Operations serialize to keep project selection and guarded writes consistent. It is not a hosted or multiuser service.

Every JSON response carries `X-Closure-API: closure-viewer/0.2`. The bundled client sends the same header and refuses a missing or different response version. A mismatching request version returns HTTP 409. The server also accepts requests that omit this header during the preview. Protocol versioning is independent of the URL path.

| Method/path | Request | Response |
| --- | --- | --- |
| GET `/api/version` | none | `api`, `implementation`, `source`, `supported_sources`, `runner`, `execution` and the session's `trusted` flag |
| GET `/api/project` | optional scenario, configuration, report query | Source model, current plan or historical report, project list, trusted state, session write token |
| GET `/api/explain` | id, optional context/report | Requirement assessment and causal paths |
| GET `/api/compare` | `base` and `report` IDs of sealed snapshots from the same project and context | Requirement and project changes since `base`, and execution or reuse decisions for `report` |
| GET `/api/history` | none | Saved report/run summaries and integrity results |
| GET `/api/runs` | id | Sealed historical run |
| GET `/api/source` | module, optional report | Current authored text or saved normalized contract |
| GET `/api/artifacts/<sha256>` | optional type/download | Verified artifact bytes; restricted content types |
| POST `/api/open` | path relative to configured workspace | Newly selected project snapshot |
| POST `/api/parameters` | project, source_hash, changes | Guarded atomic parameter patch result |
| POST `/api/verify` | project, optional scenario/configuration/force | Saved assessment, including open gates and failed analyses |
| POST `/api/build` | same as verify | Compatibility alias |

`GET /api/version` lists `closure/0.1` and `closure/0.2` in `supported_sources`. Its `source` field identifies the 0.1 core format, and `runner` is `closure-run/0.1` for both. A composed report includes `projects` and `gates`. Verification also records the source revision and assessment comparison.

POST bodies are JSON objects limited to 1 MB and require the session's `X-Closure-Token` from a project snapshot. Host must name localhost or 127.0.0.1 with the actual port. If present, Origin must identify a permitted local HTTP origin on that port. Use `path` to select a project with `/api/open`. Parameter edits and verification require a matching `project` value, return HTTP 409 for a stale selection, and reject a historical `report` ID. Verify accepts a JSON boolean for `force` and requires a server started with `--trusted`.

HTTP 200 means the operation completed; inspect `gate`, per-analysis state and diagnostics to determine engineering success. Invalid input/engine errors return 400, invalid local credentials/origin return 403, unknown operations/files return 404 and stale project/version selection returns 409. Errors use `{error: {code, message, location}}` for engine diagnostics and `{error: string}` for HTTP-layer problems. Clients must handle both. JSON responses are not cached.

The server has no public-network authentication, isolation, remote job queue or arbitrary API compatibility promise. Static exported reports can be hosted independently; running analyses stays on the user's trusted machine.
