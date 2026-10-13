"""Discoverable command help and project selection for the terminal interface."""
import argparse
import re
from pathlib import Path

from . import __version__
from .io import ClosureError


COMMANDS = {
    "check": ("Validate source files and their connections; run no analyses.", "closure check\nclosure check --json"),
    "plan": ("Show reusable evidence and analyses needing execution; run nothing.", "closure plan\nclosure plan --scenario surge\nclosure plan --base HEAD"),
    "verify": ("Run affected analyses, propagate results, and evaluate requirements.", "closure verify --trusted\nclosure verify --trusted --force\nclosure verify --scenario surge --trusted --json"),
    "set": ("Change one base input, preserving its type, metadata, and units.", 'closure set workload.arrival_rate 250\nclosure set workload.arrival_rate 250 --unit "1/s"\nclosure set workload.arrival_rate 160 --reason "Measured sustained traffic"'),
    "explain": ("Explain one requirement's verdict, evidence, and dependency paths.", "closure explain operations.CAP-001\nclosure explain operations.CAP-001 --scenario surge"),
    "inspect": ("Read a parameter, output, analysis, requirement, or module contract.", "closure inspect workload.arrival_rate\nclosure inspect platform.capacity --json"),
    "impact": ("List downstream elements that can be affected by an input or output.", "closure impact workload.arrival_rate"),
    "format": ("Format YAML/JSON concisely without changing the compiled model.", "closure format\nclosure format --check"),
    "history": ("List saved evidence, or inspect an immutable report or analysis run.", "closure history\nclosure history --report REPORT_ID\nclosure history --run RUN_ID"),
    "export": ("Export a portable HTML/JSON report with its evidence artifacts.", "closure export --output reports/review-01\nclosure export --report REPORT_ID --output reports/snapshot-01"),
    "sweep": ("Verify all points in a declared parameter study.", "closure sweep studies/capacity.yaml --trusted"),
    "approve-baseline": ("Record a human review of requirements, scope, policy, and limits.", 'closure approve-baseline --reviewer "Your name" --reason "Reviewed initial obligations"'),
    "review": ("Record an acceptance decision for one requirement's current evidence.", 'closure review operations.CAP-001 --decision accepted --reviewer "Your name" --reason "Reviewed evidence"'),
    "patch": ("Apply a JSON input patch guarded by an expected source hash.", 'closure patch --expected-hash HASH --changes-file changes.json'),
    "init": ("Create a new project from a bundled starter.", "closure init --project my-project\nclosure init --project power-project --template power"),
    "serve": ("Open the local project viewer server.", "closure serve --trusted\nclosure serve --project examples/service --workspace examples --trusted"),
    "schema": ("Write the versioned source and runtime JSON schemas.", "closure schema --output schema"),
    "completion": ("Print a shell completion script; does not change shell settings.", 'closure completion powershell | Out-String | Invoke-Expression\nsource <(closure completion bash)'),
    "build": ("Compatibility alias for verify.", "closure build --trusted"),
}


class UsageError(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Engineering inputs commonly use negative scientific notation.
        self._negative_number_matcher = re.compile(r"^-\d*\.?\d+(?:[eE][+-]?\d+)?$")

    def error(self, message):
        raise UsageError(f"{message}\nTry '{self.prog} --help'.")


def common(parser, root=False):
    default = None if root else argparse.SUPPRESS
    parser.add_argument("--project", "-p", default=default,
                        help="Project folder or manifest (default: nearest enclosing project)")
    parser.add_argument("--json", action="store_true", default=False if root else argparse.SUPPRESS,
                        help="Emit structured JSON only; suppress progress")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--quiet", "-q", action="store_true", default=False if root else argparse.SUPPRESS,
                       help="Suppress human results and progress; keep errors and exit codes")
    group.add_argument("--verbose", "-v", action="store_true", default=False if root else argparse.SUPPRESS,
                       help="Include recorded inputs, outputs, and run IDs")
    parser.add_argument("--version", action="version", version=f"closure {__version__}")


def make_parser():
    parser = Parser(prog="closure", description="Connect engineering inputs, analyses, and evidence to requirements.",
                    formatter_class=argparse.RawDescriptionHelpFormatter,
                    epilog="Everyday workflow:\n  closure check\n  closure set INPUT VALUE\n  closure plan\n  closure verify --trusted\n  closure explain REQUIREMENT\n\n"
                           "Run inside a project or any subdirectory, or select one with -p PATH.\n"
                           "Use 'closure help COMMAND' for examples and options.\n"
                           "Exit codes: 0 success/pass, 1 open verification gate or failed check,\n"
                           "            2 input/setup error, 130 interrupted.\n"
                           "--json is the machine interface. Human progress/errors go to stderr.")
    common(parser, root=True)
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    parsers = {}
    for name, (description, examples) in COMMANDS.items():
        extra = ""
        if name == "set":
            extra = ("\nEdits the base source value; scenario/configuration overrides take precedence.\n"
                     "Units default to the declared unit. Booleans accept true/false. Strings and\n"
                     "enum values are literal text. Artifact values are paths relative to the project.\n"
                     "Changing a requirement limit requires a new baseline review.\n"
                     "For several atomic edits or automation, use 'closure patch --help'.")
        if name == "patch":
            extra = '\nRead source_hash from closure check --json. The changes object maps IDs to\ndatum objects, e.g. {"workload.arrival_rate": {"value": 250, "unit": "1/s"}}.\nUse --changes-file - to read JSON from stdin. Prefer closure set for one value.'
        if name in ("verify", "build"):
            extra = "\n--trusted permits executing the project's analysis programs. Unchanged evidence\nis reused; --force reruns every analysis in the selected context. A completed\nanalysis can still produce a failing engineering requirement (exit 1)."
        if name == "init":
            extra = "\nThe destination defaults to the current directory; init never selects a parent project."
        command = sub.add_parser(name, help=description, description=description,
                                 epilog="Examples:\n  " + examples.replace("\n", "\n  ") + extra,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
        parsers[name] = command
        common(command)
        if name in ("plan", "build", "verify", "explain", "export", "review"):
            command.add_argument("--scenario", help="Declared scenario (default: first in project)")
            command.add_argument("--configuration", help="Declared configuration (default: first in project)")
        if name in ("build", "verify", "sweep", "serve"):
            command.add_argument("--trusted", action="store_true", help="Allow execution of project analysis programs")
        if name in ("build", "verify"):
            command.add_argument("--force", action="store_true", help="Rerun all analyses, including those with current evidence")
        if name == "format":
            command.add_argument("--check", action="store_true", help="Read-only style check; exit 1 when formatting is needed")
        if name == "serve":
            command.add_argument("--port", type=int, default=8765, help="Local HTTP port (default: 8765)")
            command.add_argument("--workspace", help="Folder containing projects to list in the viewer")
        if name == "init":
            command.add_argument("--template", choices=["minimal", "power"], default="minimal", help="Starter template (default: minimal, domain-neutral)")
        if name in ("explain", "inspect", "impact", "review", "set"):
            command.add_argument("identifier", help="Qualified identifier, such as workload.arrival_rate")
        if name == "set":
            command.add_argument("value", help="New value, or project-relative artifact path; quote text with spaces")
            command.add_argument("--unit", help="Unit for a quantity (must be compatible with the declared unit)")
            command.add_argument("--reason", help="Replace the input rationale with this explanation")
            command.add_argument("--expected-hash", help="Optional source hash for optimistic concurrency control")
        if name == "sweep":
            command.add_argument("study", help="Study file, relative to the project root")
        if name in ("approve-baseline", "review"):
            command.add_argument("--reviewer", required=True, help="Name of the person reviewing the obligations or evidence")
            command.add_argument("--reason", required=True, help="Explanation for this review decision")
        if name == "review":
            command.add_argument("--decision", choices=["accepted", "waived", "rejected", "not_applicable"], required=True, help="Acceptance decision")
        if name == "plan":
            command.add_argument("--base", help="Compare semantic changes with a Git revision, e.g. HEAD")
        if name == "patch":
            command.add_argument("--expected-hash", required=True, help="source_hash from closure check --json")
            changes = command.add_mutually_exclusive_group(required=True)
            changes.add_argument("--changes", help="Inline JSON mapping input IDs to datum objects")
            changes.add_argument("--changes-file", help="JSON file (relative to current directory), or - for stdin")
        if name == "schema":
            command.add_argument("--output", default="schema", help="Destination directory (default: schema)")
        if name == "export":
            command.add_argument("--output", required=True, help="New destination folder for the portable report")
            command.add_argument("--report", help="Export a saved snapshot by ID instead of the current project")
        if name == "history":
            selection = command.add_mutually_exclusive_group()
            selection.add_argument("--report", help="Inspect a saved verification report by ID")
            selection.add_argument("--run", help="Inspect an immutable analysis run by ID")
        if name == "completion":
            command.add_argument("shell", choices=["bash", "powershell"], help="Shell to generate completion for")
    help_parser = sub.add_parser("help", help="Show help for a command, including examples.")
    help_parser.add_argument("topic", nargs="?", choices=list(COMMANDS), help="Command to explain")
    return parser, parsers


def project_path(explicit=None):
    if explicit is not None:
        return Path(explicit).resolve()
    current = Path.cwd()
    for parent in (current, *current.parents):
        if any((parent / name).is_file() for name in ("project.yaml", "project.yml", "project.json")):
            return parent
    raise ClosureError("No Closure project found in this directory or its parents. Use -p PATH, or closure init --project PATH.", "PROJECT_NOT_FOUND")
