from __future__ import annotations

import difflib
import json
import math
import os
import shutil
import sys
from pathlib import Path
from pydantic import ValidationError

from .cli_args import UsageError, make_parser, project_path
from .cli_output import render
from .editing import patch_parameters, project_lock
from .engine import Engine, approve_baseline, record_review, sweep
from .io import ClosureError, atomic_json
from .models import Datum
from .schemas import schemas
from .project import Project


def emit(value, as_json=False, *, command=None, root=None, quiet=False, verbose=False):
    if as_json:
        print(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False))
    elif not quiet:
        print(render(value, command, root, verbose))


def execution_progress(event):
    label = {"running": "RUN", "completed": "DONE", "cached": "CACHED", "blocked": "BLOCKED", "error": "ERROR"}[event["event"]]
    detail = f" ({event['reason']})" if "reason" in event else f" ({event['seconds']:.2f}s)" if "seconds" in event else ""
    if "error" in event:
        detail = f": {event['error']['message']}"
    context = event["context"]
    point = f"{context['point']} / {context['scenario']} / {context['configuration']} " if context["point"] != "baseline" else ""
    print(f"{point}[{event['index']}/{event['total']}] {label:7} {event['analysis']}{detail}", file=sys.stderr, flush=True)


def set_parameter(project, args):
    if args.identifier not in project.parameters:
        raise ClosureError(f"Unknown input {args.identifier}; use closure inspect or shell completion to find an input.", "UNKNOWN_REF")
    original = project.parameters[args.identifier]
    replacement = original.model_dump()
    if args.unit is not None:
        if original.type != "quantity":
            raise ClosureError("--unit is only valid for quantity inputs", "TYPE_MISMATCH")
        replacement["unit"] = args.unit
    if original.type in ("quantity", "scalar"):
        try:
            number = float(args.value)
            if not math.isfinite(number):
                raise ValueError()
            replacement["value"] = int(args.value) if args.value.lstrip("+-").isdigit() else number
        except ValueError as exc:
            raise ClosureError(f"{args.identifier} requires a finite number", "INPUT_ERROR") from exc
    elif original.type == "boolean":
        if args.value.lower() not in ("true", "false"):
            raise ClosureError(f"{args.identifier} requires true or false", "INPUT_ERROR")
        replacement["value"] = args.value.lower() == "true"
    elif original.type == "artifact":
        replacement["path"] = args.value
    else:
        replacement["value"] = args.value
    if args.reason is not None:
        replacement["rationale"] = args.reason
    updated = Datum.model_validate(replacement)
    expected = project.source_hash if args.expected_hash is None else args.expected_hash
    result = patch_parameters(project.manifest_path, expected, {args.identifier: replacement})
    result.update(before=original.model_dump(), after=updated.model_dump(),
                  obligation_change=original != updated and args.identifier in project.protected_parameters())
    return result


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in argv
    args, project = None, None
    try:
        if argv and argv[0] in ("_complete", "_complete-json"):
            from .cli_completion import candidates
            words = json.load(sys.stdin) if argv[0] == "_complete-json" else argv[2:] if argv[1:2] == ["--"] else argv[1:]
            if not isinstance(words, list) or not all(isinstance(w, str) for w in words):
                return 0
            print("\n".join(candidates(words)))
            return 0
        parser, commands = make_parser()
        args = parser.parse_args(argv)
        as_json = args.json
        if args.quiet and args.verbose:
            raise UsageError("--quiet and --verbose cannot be combined.")
        if args.command is None or args.command == "help":
            (commands[args.topic] if getattr(args, "topic", None) else parser).print_help()
            return 0
        if args.command == "completion":
            from .cli_completion import SCRIPTS
            if as_json:
                emit({"shell": args.shell, "script": SCRIPTS[args.shell]}, True)
            else:
                print(SCRIPTS[args.shell], end="")
            return 0
        if args.command == "schema":
            for name, schema in schemas().items():
                atomic_json(Path(args.output) / f"{name}.schema.json", schema)
            result = {"schemas": str(Path(args.output).resolve())}
            root = None
        elif args.command == "init":
            # Initialization always uses the requested/current folder, never an ancestor.
            root = Path(args.project or ".").resolve()
            template = Path(__file__).parent / "templates" / args.template
            if any((root / name).exists() for name in ("project.yaml", "project.yml", "project.json")):
                raise ClosureError("Project already exists", "PROJECT_EXISTS")
            collisions = [p.relative_to(template) for p in template.rglob("*") if p.is_file() and (root / p.relative_to(template)).exists()]
            if collisions:
                raise ClosureError("Starter would overwrite existing files: " + ", ".join(map(str, collisions)), "PROJECT_EXISTS")
            shutil.copytree(template, root, dirs_exist_ok=True)
            from .formatting import format_project
            format_project(root)
            result = {"created": str(root), "next": f'closure approve-baseline --project "{root}" --reviewer YOUR_NAME --reason "Initial scope review"'}
        else:
            path = project_path(args.project)
            root = path if path.is_dir() else path.parent
            if args.command == "serve":
                if as_json:
                    raise UsageError("serve is an interactive server, not a JSON command; omit --json.")
                from .viewer_server import serve
                serve(path, args.port, args.workspace, args.trusted)
                return 0
            if args.command == "history":
                from .evidence import EvidenceStore
                store = EvidenceStore(root)
                result = {"mode": "historical", "report": store.load_report(args.report)} if args.report else (
                    {"mode": "historical", "run": store.load_run(args.run)} if args.run else store.history())
            elif args.command == "export" and args.report:
                from .reporting import export_report
                result = export_report(path, args.output, args.report)
            elif args.command == "format":
                from .formatting import format_project
                result = format_project(path, check=args.check)
            else:
                project = Project(path)
                if args.command in ("plan", "build", "verify", "explain", "export", "review"):
                    engine = Engine(project, args.scenario, args.configuration)
                progress = None if as_json or args.quiet else execution_progress
                if args.command == "check":
                    result = project.check()
                elif args.command == "plan":
                    result = engine.plan()
                    if args.base:
                        from .comparison import compare_git
                        result["base_comparison"] = compare_git(project, args.base)
                elif args.command in ("build", "verify"):
                    if progress:
                        print(f"Verifying {project.manifest.name or project.manifest.project} | {engine.context['scenario']} / {engine.context['configuration']}", file=sys.stderr, flush=True)
                    result = engine.verify(trusted=args.trusted, force=args.force, progress=progress)
                elif args.command == "export":
                    from .reporting import export_report
                    result = export_report(engine, args.output)
                elif args.command == "explain":
                    result = engine.explain(args.identifier)
                elif args.command == "impact":
                    result = project.impact(args.identifier)
                elif args.command == "inspect":
                    item = project.parameters.get(args.identifier) or project.analyses.get(args.identifier) or project.requirements.get(args.identifier) or project.modules.get(args.identifier) or project.ports.get(args.identifier)
                    if item is None:
                        raise ClosureError(f"Unknown identifier {args.identifier}", "UNKNOWN_REF")
                    result = {"id": args.identifier, "source": project.locations.get(args.identifier), "contract": item.model_dump(by_alias=True)}
                elif args.command == "sweep":
                    result = sweep(project, args.study, trusted=args.trusted, progress=progress)
                elif args.command == "approve-baseline":
                    with project_lock(project.root):
                        result = approve_baseline(project, args.reviewer, args.reason)
                elif args.command == "review":
                    with project_lock(project.root):
                        result = record_review(engine, args.identifier, args.decision, args.reviewer, args.reason)
                elif args.command == "set":
                    result = set_parameter(project, args)
                elif args.command == "patch":
                    data = args.changes if args.changes is not None else sys.stdin.read() if args.changes_file == "-" else Path(args.changes_file).read_text(encoding="utf-8-sig")
                    changes = json.loads(data)
                    if not isinstance(changes, dict) or not changes or not all(isinstance(v, dict) for v in changes.values()):
                        raise ClosureError("Changes must be a nonempty JSON object mapping input IDs to datum objects", "INPUT_ERROR")
                    result = patch_parameters(path, args.expected_hash, changes)
        if args.quiet and not as_json and args.command == "check":
            for diagnostic in result["diagnostics"]:
                if diagnostic.get("severity") != "warning":
                    print(f"error[{diagnostic['code']}]: {diagnostic['message']}", file=sys.stderr)
        if args.quiet and not as_json and args.command in ("verify", "build", "sweep"):
            reports = result["reports"] if args.command == "sweep" else [result]
            for report in reports:
                for analysis in report["analyses"]:
                    if analysis.get("error"):
                        print(f"error[{analysis['error']['code']}]: {analysis['id']}: {analysis['error']['message']}", file=sys.stderr)
        emit(result, as_json, command=args.command, root=root, quiet=args.quiet, verbose=args.verbose)
        return 1 if result.get("valid") is False or (args.command in ("build", "verify") and not result["gate"]) or (args.command == "sweep" and result["failed"]) or (args.command == "format" and args.check and not result["clean"]) else 0
    except (ClosureError, UsageError, ValueError, OSError) as exc:
        if isinstance(exc, BrokenPipeError):
            # Avoid a second broken-pipe exception during interpreter shutdown.
            try:
                with open(os.devnull, "w") as sink:
                    os.dup2(sink.fileno(), sys.stdout.fileno())
            except (OSError, ValueError):
                pass
            return 0
        if argv and argv[0] in ("_complete", "_complete-json"):
            return 0
        error = exc.as_dict() if isinstance(exc, ClosureError) else {"code": "USAGE_ERROR" if isinstance(exc, UsageError) else "INPUT_ERROR", "message": str(exc)}
        if as_json:
            emit({"error": error}, True)
        else:
            message = error["message"]
            if isinstance(exc, ValidationError):
                message = "; ".join((".".join(map(str, item["loc"])) + ": " if item["loc"] else "") + item["msg"]
                                    for item in exc.errors(include_url=False, include_context=False, include_input=False))
            print(f"error[{error['code']}]: {message}", file=sys.stderr)
            if error.get("location"):
                print(f"  at {error['location']}", file=sys.stderr)
            if error["code"] == "TRUST_REQUIRED":
                print("Use --trusted to allow this project's analysis programs to run.", file=sys.stderr)
            if error["code"] == "UNKNOWN_CONTEXT" and project:
                print("Scenarios: " + ", ".join(project.manifest.scenarios) + "\nConfigurations: " + ", ".join(project.manifest.configurations), file=sys.stderr)
            if error["code"] == "UNKNOWN_REF" and project:
                matches = difflib.get_close_matches(getattr(args, "identifier", ""), project.locations.keys() | project.ports.keys(), n=3)
                if matches:
                    print("Did you mean: " + ", ".join(matches) + "?", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        if as_json:
            emit({"error": {"code": "INTERRUPTED", "message": "Interrupted by user"}}, True)
        else:
            print("Interrupted.", file=sys.stderr)
        return 130
