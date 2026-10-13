# Service capacity and energy

This non-CAD example connects workload, platform and operations contracts through the same Closure compiler, runner, evidence store and viewer used by the other engineering projects.

For an interactive terminal walkthrough, activate the Closure environment and run from this directory:

```powershell
closure verify --trusted
closure set workload.arrival_rate 250
closure plan
closure verify --trusted
closure explain operations.CAP-001
closure set workload.arrival_rate 160
closure verify --trusted
```

The 250 requests/s case has -4.17% headroom and fails capacity. Only capacity reruns when matching evidence is unavailable; energy remains 180 W. Restoring 160 reuses the matching baseline. Verify reports execution/reuse and the saved evidence path. See the [CLI guide](../../docs/CLI_GUIDE.md) for help, completion, JSON, exit codes, and unit-preserving edits.

Run from the repository root:

```powershell
.\.venv\Scripts\closure.exe check --project examples/service
.\.venv\Scripts\closure.exe build --project examples/service --trusted
.\.venv\Scripts\closure.exe serve --project examples/service --workspace examples --trusted
```

The default `routine / balanced` context has four workers, 160 requests/s, 33.33% throughput headroom and 180 W equipment power. Both requirements pass. `surge / balanced` raises traffic to 260 requests/s and fails the 20% headroom criterion. `surge / expanded` uses six workers, giving 27.78% headroom and 260 W; both criteria pass.

These are linear planning estimates with assumed worker throughput and power. They do not establish queue latency, production reliability or availability.

Changing `workload.arrival_rate` marks only the capacity branch stale. The energy branch remains current. Rebuilding produces the new verdict, and `explain operations.CAP-001` traces the cross-module dependency. Restoring the input reuses matching intact evidence.

```powershell
.\.venv\Scripts\closure.exe build --project examples/service --scenario surge --configuration balanced --trusted
.\.venv\Scripts\closure.exe explain --project examples/service --scenario surge --configuration balanced operations.CAP-001
.\.venv\Scripts\closure.exe sweep --project examples/service studies/capacity.yaml --trusted
```

The six-point study varies traffic and worker count. Three points pass and three fail; all six have complete evidence. Failed builds and studies intentionally return exit code 1.

The viewer offers requirements, variables, module interfaces, analysis evidence and history. Its overview shows closure work without an empty model panel. Other projects gain 3D controls from their own artifacts.

The portable report (development record) preserves a routine baseline and CSV evidence. Recorded verification (development record) identifies the case reports and study results. Tests in `tests/test_general_projects.py` additionally exercise JSON authoring, the real HTTP API, neutral project initialization, stale evidence, recovery and export.

Public source archives omit development evidence stores and generated deliverables. Run Verify in your environment, then `closure export --output NEW_FOLDER` to create an inspectable report from your own run.
