# Closure on the command line

The everyday loop is **check → set → plan → verify → explain**. Commands find the
nearest project in the current directory or its parents. Use `-p PATH` to select
a folder or an explicit `project.yaml`, `project.yml`, or `project.json` instead.
An explicit path never silently falls back to another project.

## Get started

Install the package into a Python environment. For this source checkout, from the
repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\Activate.ps1
closure --version
closure --help
closure help verify
```

In Bash, activate with `source .venv/bin/activate`. Activation is optional: the
executable is also available at `.venv/Scripts/closure.exe` on Windows or
`.venv/bin/closure` on Linux. `python -m closure` uses the selected interpreter.

`closure` by itself displays help. Every command has descriptions, option help,
and examples through `closure help COMMAND` or `closure COMMAND --help`.

## Try the service project

```powershell
cd examples/service
closure check
closure verify --trusted
closure inspect workload.arrival_rate
closure set workload.arrival_rate 250
closure plan
closure verify --trusted
closure explain operations.CAP-001
```

`check` validates source and connections. `plan` assesses available evidence and
lists what needs to run, without executing analyses. `verify` refreshes affected
analyses, propagates results, evaluates requirements, and saves a report.
`--trusted` explicitly permits running the project's analysis programs.

Starting from the routine/balanced baseline, changing 160 to 250 requests/s makes
capacity evidence stale. Power is independent of arrival rate and stays current.
A new execution prints progress as each analysis starts, completes, or reuses
evidence, followed by a summary like:

```text
[1/2] RUN     platform.capacity (stale)
[1/2] DONE    platform.capacity (...s)
[2/2] CACHED  platform.energy

RAN          platform.capacity
CACHED       platform.energy
Execution: 1 ran, 1 reused, 0 errors, 0 blocked.

FAIL         operations.CAP-001
  Sustained throughput shall retain the reserved capacity headroom.
  -4.16667 percent; required >= 20 percent; margin -24.1667 percent
```

The elapsed time and report ID vary. If the exact inputs, sources, context, and
environment were already verified, matching evidence is reused instead. The
report includes its absolute saved path. `closure history --report ID` reopens
that immutable snapshot; it does not claim the current project still passes.

`explain` shows the criterion, evidence freshness, execution/acceptance state,
and dependency paths such as:

```text
workload.arrival_rate -> platform.capacity -> platform.capacity.headroom -> operations.CAP-001
```

An analysis completing successfully is distinct from its engineering requirement
passing. At 250 requests/s, the calculation completes but headroom is below 20%.

Restore the baseline, or explicitly force a new execution:

```powershell
closure set workload.arrival_rate 160
closure verify --trusted
closure verify --trusted --force
closure verify --trusted --verbose
```

`--force` reruns all analyses in the selected context. `--verbose` adds recorded
inputs, outputs, and run IDs to the report. `build` remains an alias for `verify`.
Progress is per analysis; external solver logs are preserved in evidence rather
than streamed live. Analyses currently execute sequentially in dependency order.

## Change inputs safely

```powershell
closure set workload.arrival_rate 250 --unit "1/s"
closure set workload.arrival_rate 160 --reason "Measured sustained traffic"
closure impact workload.arrival_rate
```

Omitting `--unit` keeps the declared unit. An explicit unit must be compatible.
`set` preserves type, qualifiers, choices, origin, description, and rationale
unless `--reason` replaces the rationale. Booleans use `true`/`false`; string and
enum values are literal text. Artifact inputs take a project-relative path.
Invalid values and incompatible units leave the source untouched. Negative
scientific notation is accepted, for example `-1e-3`.

`set` edits the **base source value**. Scenario and configuration overrides still
take precedence; it does not silently edit a selected scenario. For example:

```powershell
closure verify --scenario surge --configuration balanced --trusted
closure verify --scenario surge --configuration expanded --trusted
```

The service surge scenario declares 260 requests/s, regardless of a different
base arrival rate. Balanced fails headroom; expanded uses six workers and passes.

Changing an input that defines a requirement limit is allowed, but invalidates
the reviewed obligation baseline. The CLI calls this out; review the changed
criterion before recording a new baseline with `approve-baseline`.

For several edits or automation, `patch` retains optimistic concurrency control:

```powershell
$state = closure check --json | ConvertFrom-Json
closure patch --expected-hash $state.source_hash --changes-file changes.json
```

The file contains an object such as
`{"workload.arrival_rate": {"value": 250, "unit": "1/s"}}`. Use `--changes-file -`
for stdin or the existing `--changes` option for inline JSON. File paths are
relative to the current shell directory. A stale source hash rejects the whole
patch. `set` automatically guards against concurrent edits and also accepts an
explicit `--expected-hash` for callers that prepared a change earlier.

## Scripts and CI

Human results go to stdout; progress and human errors go to stderr. Use `--json`
for one structured JSON result on stdout and no progress. Existing report,
evidence, impact, and inspection JSON shapes are preserved. JSON errors, including
argument errors, are objects with an `error` field on stdout. Help, version, and
completion scripts are informational commands; `serve` does not support JSON.

```powershell
$report = closure verify --trusted --json | ConvertFrom-Json
$verificationExit = $LASTEXITCODE
$report.executed
$report.counts
```

`--quiet` suppresses human results and progress while retaining errors and exit
codes. `--quiet --json` still emits JSON. Avoid parsing human output in scripts.

| Code | Meaning |
| --- | --- |
| 0 | Command succeeded; Verify gate passed |
| 1 | Verify gate open, invalid static check, study has open points, or formatting needed with `format --check` |
| 2 | Invalid arguments/input, missing project, missing trust, or command setup error |
| 130 | User interruption (Ctrl+C) |

`plan` and `explain` return 0 when inspection succeeds, even if the gate is open.
Use `verify` to gate CI. A solver failure recorded in a verification report is an
open gate (1); an invocation rejected before execution is an input/setup error (2).

## Tab completion

Load completion for the current shell session after activating the environment:

```powershell
closure completion powershell | Out-String | Invoke-Expression
```

```bash
source <(closure completion bash)
```

Completion suggests commands, flags, parameter/requirement identifiers, enum and
Boolean values, and declared scenarios/configurations. It reads project contracts
without running analyses. The command only prints a script; Closure does not edit
shell profiles. Add the loading command to your profile yourself if desired.

## Other useful commands

```powershell
closure format --check
closure history
closure export --output reports/review-01
closure sweep studies/capacity.yaml --trusted
closure init --project my-project
```

Exports require a new destination folder. Study paths are relative to the project
root. `init` always targets the requested/current folder, even inside an existing
project. History remains inspectable when current source files are invalid.
