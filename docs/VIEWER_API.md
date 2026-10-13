# Local viewer API: closure-viewer/0.1

This provisional API is bundled with `closure-se==0.1.0a1`. Use the matching viewer assets. It serves one selected project per local server session; project selection affects all tabs. Operations serialize to keep project selection and guarded writes consistent. It is not a hosted or multiuser service.

Every JSON response carries `X-Closure-API: closure-viewer/0.1`. The bundled client sends the same header and refuses a missing/different response version. A mismatching request version returns HTTP 409. Legacy requests without the header remain accepted during this preview; new clients should send it. `GET /api/version` reports API, implementation, source, runner and trusted-execution metadata. Protocol versioning is independent of the URL path.

| Method/path | Request | Response |
| --- | --- | --- |
| GET `/api/project` | optional scenario, configuration, report query | Source model, current plan or historical report, project list, trusted state, session write token |
| GET `/api/explain` | id, optional context/report | Requirement assessment and causal paths |
| GET `/api/history` | none | Saved report/run summaries and integrity results |
| GET `/api/runs` | id | Sealed historical run |
| GET `/api/source` | module, optional report | Current authored text or saved normalized contract |
| GET `/api/artifacts/<sha256>` | optional type/download | Verified artifact bytes; restricted content types |
| POST `/api/open` | path relative to configured workspace | Newly selected project snapshot |
| POST `/api/parameters` | project, source_hash, changes | Guarded atomic parameter patch result |
| POST `/api/verify` | project, optional scenario/configuration/force | Saved assessment, including open gates and failed analyses |
| POST `/api/build` | same as verify | Compatibility alias |

POST bodies are JSON objects limited to 1 MB and require `X-Closure-Token` from a current snapshot. Host must be localhost/127.0.0.1 with the actual port; an Origin header must match that local origin. `project` must match the selected project; otherwise HTTP 409. A `report` in a write body is rejected because snapshots are read-only. `force` is a real JSON boolean. Verify additionally requires a server started with `--trusted`.

HTTP 200 means the operation completed; inspect `gate`, per-analysis state and diagnostics to determine engineering success. Invalid input/engine errors return 400, invalid local credentials/origin return 403, unknown operations/files return 404 and stale project/version selection returns 409. Errors use `{error: {code, message, location}}` for engine diagnostics and `{error: string}` for HTTP-layer problems. Clients must handle both. JSON responses are not cached.

The server has no public-network authentication, isolation, remote job queue or arbitrary API compatibility promise. Static exported reports can be hosted independently; running analyses stays on the user's trusted machine.
