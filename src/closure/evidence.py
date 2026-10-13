from __future__ import annotations

import ast
import importlib.metadata
import json
import os
import platform
import re
import shutil
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from .io import ClosureError, atomic_json, canonical, digest, file_digest, read_json, within
from .units import validate_value
from .processes import managed_process
from .protocol import EvidenceRecord, Report, RunnerRequest, RunnerResponse


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def environment_identity():
    return {"python": sys.version, "interpreter": os.path.abspath(sys.executable),
            "platform": platform.platform(),
            "engine_sources": {p.name: file_digest(p) for p in sorted(Path(__file__).parent.glob("*.py"))},
            "process_environment": {k: os.environ.get(k) for k in ("PATH", "SystemRoot", "WINDIR", "PATHEXT")},
            "packages": sorted((d.metadata.get("Name", ""), d.version) for d in importlib.metadata.distributions())}


def source_snapshot(project, analysis):
    found = set()
    for pattern in analysis.run.sources + ([analysis.run.environment_lock] if analysis.run.environment_lock else []):
        target = within(project.root, pattern)
        matches = [target] if target.exists() else sorted(project.root.glob(pattern))
        if not matches:
            raise ClosureError(f"Source not found: {pattern}", "MISSING_SOURCE")
        for match in matches:
            for path in match.rglob("*") if match.is_dir() else [match]:
                if path.is_file() and not any(p in ("__pycache__", ".closure", ".venv", ".git") for p in path.relative_to(project.root).parts):
                    if path.is_symlink() or not path.resolve().is_relative_to(project.root):
                        raise ClosureError("Source symlinks must resolve inside the project", "PATH_ESCAPE")
                    found.add(path)
    # Capture statically resolvable transitive local Python imports without importing them.
    pending, visited = list(found), set()
    while pending:
        path = pending.pop()
        if path.suffix != ".py" or path in visited:
            continue
        visited.add(path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        except (SyntaxError, UnicodeError) as exc:
            raise ClosureError(f"Invalid Python source {path}: {exc}", "SOURCE_PARSE") from exc
        for node in ast.walk(tree):
            names = [n.name for n in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            for name in names:
                bases = [path.parent, project.root]
                if isinstance(node, ast.ImportFrom) and node.level:
                    base = path.parent
                    for _ in range(node.level - 1):
                        base = base.parent
                    bases = [base]
                for base in bases:
                    module_path = base.joinpath(*name.split("."))
                    candidates = [module_path.with_suffix(".py"), module_path / "__init__.py"]
                    if isinstance(node, ast.ImportFrom):
                        candidates.extend(module_path / (alias.name + ".py") for alias in node.names)
                    for candidate in candidates:
                        if candidate.is_file() and candidate.resolve().is_relative_to(project.root) and candidate not in found:
                            found.add(candidate)
                            pending.append(candidate)
    return {str(p.relative_to(project.root)).replace("\\", "/"): file_digest(p) for p in sorted(found)}


def resolve_executable(argv):
    name = argv[0]
    executable = sys.executable if name in ("python", "python3", "{python}") else shutil.which(name)
    if executable is None:
        raise ClosureError(f"Executable unavailable: {name}", "EXECUTABLE_MISSING")
    # Invoked paths carry meaning: following a virtualenv Python symlink would
    # select the base interpreter and silently discard its installed packages.
    # Hashing the path still reads the target bytes without changing argv[0].
    return [os.path.abspath(executable), *argv[1:]]


def tool_identity(run, root):
    """Fingerprint declared external tools without launching version probes.

    CLOSURE_TOOL_<NAME> provides a machine-local executable override, so authored
    contracts can keep portable tool names. The resolved path and bytes form the key.
    """
    executables = {}
    for alias, command in run.tools.items():
        if not alias.replace("_", "").isalnum():
            raise ClosureError(f"Invalid tool alias: {alias}", "TOOL_INVALID")
        requested = os.environ.get("CLOSURE_TOOL_" + alias.upper(), command)
        executable = resolve_executable([requested])[0]
        executables[alias] = {"path": executable, "sha256": file_digest(executable)}
    dependencies = {}
    for declared in run.tool_files:
        path = (root / declared).resolve()
        if not path.is_file():
            raise ClosureError(f"Declared tool dependency missing: {declared}", "TOOL_MISSING")
        dependencies[str(path)] = file_digest(path)
    return {"executables": executables, "files": dependencies}


class EvidenceStore:
    def __init__(self, root: Path):
        self.root = root / ".closure"

    def index(self):
        path = self.root / "index.json"
        return read_json(path) if path.exists() else {"keys": {}, "history": {}}

    def artifact_path(self, value):
        checksum = value.get("sha256", "")
        if not isinstance(checksum, str) or not re.fullmatch(r"[a-f0-9]{64}", checksum):
            raise ClosureError("Invalid artifact content identity", "ARTIFACT_INVALID")
        path = within(self.root, f"artifacts/{checksum}")
        if not path.is_file():
            raise ClosureError(f"Recorded artifact is missing: {checksum}", "ARTIFACT_MISSING")
        if file_digest(path) != checksum:
            raise ClosureError(f"Recorded artifact bytes do not match {checksum}", "ARTIFACT_CORRUPT")
        return path

    def archive_artifact(self, source, checksum):
        destination = self.root / "artifacts" / checksum
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_file() and file_digest(destination) == checksum:
            return destination
        token = uuid.uuid4().hex
        if destination.exists():
            quarantine = self.root / "quarantine" / f"{checksum}-{token}"
            quarantine.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(destination, quarantine)
        temporary = destination.with_name(f"{checksum}.{token}.tmp")
        try:
            shutil.copy2(source, temporary)
            if file_digest(temporary) != checksum:
                raise ClosureError("Artifact changed while storing its evidence", "ARTIFACT_CONFLICT")
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return destination

    def _read_history(self, collection, identifier):
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise ClosureError("Invalid history identity", "HISTORY_ID")
        path = within(self.root, f"{collection}/{identifier}.json")
        if not path.is_file():
            raise ClosureError(f"Historical {collection} entry is missing: {identifier}", "HISTORY_MISSING")
        try:
            value = read_json(path)
            if not isinstance(value, dict) or value.get("id") != identifier:
                raise ValueError("identity mismatch")
            return value
        except (ValueError, TypeError, KeyError) as exc:
            raise ClosureError(f"Invalid historical {collection} entry: {identifier}", "HISTORY_CORRUPT") from exc

    def _verify_record(self, record, artifacts=True):
        try:
            EvidenceRecord.model_validate(record)
            body = {k: v for k, v in record.items() if k != "record_hash"}
            if record.get("protocol") != "closure-evidence/0.1" or digest(body) != record.get("record_hash"):
                raise ValueError("record digest mismatch")
            if artifacts:
                values = list(record["outputs"].values())
                if record.get("inputs_archived"):
                    values.extend(record["inputs"].values())
                for value in values:
                    if value.get("type") == "artifact":
                        self.artifact_path(value)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise ClosureError("Historical evidence record failed its integrity check", "HISTORY_CORRUPT") from exc
        return record

    def load_run(self, identifier, artifacts=True):
        return self._verify_record(self._read_history("runs", identifier), artifacts)

    def save_report(self, report):
        report = json.loads(canonical({**report, "report_hash": digest(report)}))
        Report.model_validate(report)
        path = self.root / "reports" / f"{report['id']}.json"
        if path.exists():
            raise ClosureError("Report identity collision", "RECORD_COLLISION")
        atomic_json(path, report)
        atomic_json(self.root / "report.json", report)
        return report

    def load_report(self, identifier, artifacts=True):
        report = self._read_history("reports", identifier)
        if "report_hash" not in report or "model" not in report:
            raise ClosureError("This legacy report has no sealed model snapshot. Its individual run records remain inspectable; build again to create a full snapshot.", "REPORT_UNSEALED")
        try:
            Report.model_validate(report)
            body = {k: v for k, v in report.items() if k != "report_hash"}
            if report.get("schema") != "closure-report/0.1" or digest(body) != report["report_hash"]:
                raise ValueError("report digest mismatch")
            for analysis in report["analyses"]:
                if analysis.get("record"):
                    self._verify_record(analysis["record"], artifacts)
        except (ValueError, TypeError, KeyError) as exc:
            raise ClosureError("Historical report failed its integrity check", "HISTORY_CORRUPT") from exc
        return report

    def history(self):
        result = {"reports": [], "runs": []}
        for collection, loader, fields in (
            ("reports", self.load_report, ("created_at", "name", "context", "gate", "counts", "report_hash", "source_hash")),
            ("runs", self.load_run, ("analysis", "started_at", "context", "execution", "evidence_class", "record_hash")),
        ):
            for path in sorted((self.root / collection).glob("*.json"), reverse=True):
                identifier = path.stem
                try:
                    value = loader(identifier, artifacts=False)
                    entry = {"id": identifier, "integrity": "verified", **{k: value.get(k) for k in fields}}
                except (ClosureError, OSError) as exc:
                    entry = {"id": identifier, "integrity": "unavailable", "error": exc.as_dict() if isinstance(exc, ClosureError) else {"code": "HISTORY_IO", "message": str(exc)}}
                result[collection].append(entry)
            result[collection].sort(key=lambda item: item.get("created_at") or item.get("started_at") or "", reverse=True)
        return result

    def lookup(self, key, slot):
        index = self.index()
        record_id = index["keys"].get(key)
        if record_id:
            try:
                record = self.load_run(record_id)
                if record.get("execution_key") == key:
                    return "current", record
            except (ClosureError, OSError):
                pass
            return "missing", None
        return ("stale" if index["history"].get(slot) else "missing"), None

    def invalidate(self, key):
        """Withdraw reusable support before a forced attempt; retain history."""
        index = self.index()
        if key in index["keys"]:
            del index["keys"][key]
            atomic_json(self.root / "index.json", index)

    def publish(self, record, slot):
        record = json.loads(canonical({**record, "record_hash": digest(record)}))
        EvidenceRecord.model_validate(record)
        path = self.root / "runs" / f"{record['id']}.json"
        if path.exists():
            raise ClosureError("Run identity collision", "RECORD_COLLISION")
        atomic_json(path, record)
        index = self.index()
        index["keys"][record["execution_key"]] = record["id"]
        index["history"].setdefault(slot, []).append(record["id"])
        atomic_json(self.root / "index.json", index)
        return record

    def execute(self, project, identifier, analysis, key, slot, context, inputs, source_files, environment, upstream, tools=None):
        self.root.mkdir(parents=True, exist_ok=True)
        invocation = uuid.uuid4().hex
        with tempfile.TemporaryDirectory(prefix="work-", dir=self.root) as temporary:
            snapshot = Path(temporary) / "source"
            snapshot.mkdir()
            for relative, expected in source_files.items():
                source = within(project.root, relative)
                target = within(snapshot, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                if file_digest(target) != expected:
                    raise ClosureError("Source changed while preparing execution", "SOURCE_RACE")
            run_inputs = json.loads(json.dumps(inputs))
            for name, envelope in run_inputs.items():
                if envelope.get("type") == "artifact":
                    source = Path(envelope["path"])
                    target = snapshot / ".inputs" / name / source.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                    if file_digest(target) != envelope["sha256"]:
                        raise ClosureError("Artifact changed while preparing execution", "SOURCE_RACE")
                    envelope["path"] = str(target)
            output_dir = snapshot / "outputs"
            output_dir.mkdir()
            request = {"protocol": "closure-run/0.1", "invocation_id": invocation, "inputs": run_inputs,
                       "context": context, "settings": analysis.settings, "seed": analysis.run.seed, "output_dir": str(output_dir),
                       "tools": tools or {"executables": {}, "files": {}}}
            command = resolve_executable(analysis.run.argv)
            child_env = {k: os.environ[k] for k in ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP", "COMSPEC", "PATHEXT", "USERPROFILE", "APPDATA", "LOCALAPPDATA") if k in os.environ}
            child_env.update(analysis.run.environment)
            child_env.update({"PYTHONHASHSEED": "0", "PYTHONIOENCODING": "utf-8", "CLOSURE_OUTPUT_DIR": str(output_dir),
                              "XDG_CONFIG_HOME": str(snapshot / ".config"), "XDG_CACHE_HOME": str(snapshot / ".cache"),
                              "MPLCONFIGDIR": str(snapshot / ".cache" / "matplotlib")})
            started = utcnow()
            stdout_path, stderr_path = Path(temporary) / "stdout", Path(temporary) / "stderr"
            request_path = Path(temporary) / "request.json"
            RunnerRequest.model_validate(request)
            request_path.write_bytes(canonical(request))
            with request_path.open("rb") as stdin, stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
                with managed_process(command, cwd=snapshot, stdin=stdin, stdout=stdout, stderr=stderr, env=child_env) as process:
                    deadline = time.monotonic() + analysis.run.timeout
                    while process.poll() is None:
                        if time.monotonic() > deadline or max(stdout_path.stat().st_size, stderr_path.stat().st_size) > analysis.run.max_output_bytes:
                            raise ClosureError("Analysis exceeded time or output limit", "RUN_LIMIT")
                        time.sleep(0.02)
            if max(stdout_path.stat().st_size, stderr_path.stat().st_size) > analysis.run.max_output_bytes:
                raise ClosureError("Analysis exceeded output limit", "RUN_LIMIT")
            logs = stderr_path.read_text(encoding="utf-8", errors="replace")
            if process.returncode != 0:
                raise ClosureError(f"Analysis exited {process.returncode}: {logs[-4000:]}", "RUN_ERROR")
            if tools is not None and tool_identity(analysis.run, project.root) != tools:
                raise ClosureError("External tool changed during execution", "TOOL_MUTATION")
            for relative, expected in source_files.items():
                path = within(snapshot, relative)
                if not path.is_file() or file_digest(path) != expected:
                    raise ClosureError("Analysis modified its source snapshot", "SOURCE_MUTATION")
            for value in run_inputs.values():
                if value.get("type") == "artifact":
                    path = Path(value["path"])
                    if not path.is_file() or file_digest(path) != value["sha256"]:
                        raise ClosureError("Analysis modified its copied input artifact", "INPUT_MUTATION")
            try:
                def unique_pairs(pairs):
                    result = {}
                    for key, value in pairs:
                        if key in result:
                            raise ValueError(f"Duplicate JSON key: {key}")
                        result[key] = value
                    return result
                response = json.loads(stdout_path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs,
                                      parse_constant=lambda s: (_ for _ in ()).throw(ValueError(s)))
                RunnerResponse.model_validate(response)
                if response.get("protocol") != "closure-run/0.1" or response.get("invocation_id") != invocation:
                    raise ValueError("protocol or invocation identity mismatch")
                if set(response.get("outputs", {})) != set(analysis.outputs):
                    raise ValueError("output names differ from contract")
                if analysis.solver and response.get("converged") is not True:
                    raise ValueError("solver did not converge")
                outputs = {name: validate_value(response["outputs"][name], port) for name, port in analysis.outputs.items()}
            except (ValueError, TypeError, KeyError, RecursionError) as exc:
                raise ClosureError(f"Invalid runner response: {exc}", "OUTPUT_INVALID") from exc
            for name, envelope in outputs.items():
                if envelope.get("type") == "artifact":
                    artifact = within(snapshot, envelope["path"])
                    if not artifact.is_file():
                        raise ClosureError(f"Missing produced artifact {name}", "OUTPUT_INVALID")
                    checksum = file_digest(artifact)
                    destination = self.archive_artifact(artifact, checksum)
                    outputs[name] = {"type": "artifact", "sha256": checksum, "name": artifact.name,
                                     "path": str(destination), "media_type": envelope.get("media_type", "application/octet-stream"),
                                     "qualifiers": analysis.outputs[name].qualifiers}
            for value in run_inputs.values():
                if value.get("type") == "artifact":
                    self.archive_artifact(value["path"], value["sha256"])
            record = {"id": invocation, "protocol": "closure-evidence/0.1", "analysis": identifier, "execution_key": key,
                      "started_at": started, "finished_at": utcnow(), "context": context, "inputs": inputs, "outputs": outputs,
                      "inputs_archived": True,
                      "sources": source_files, "environment": environment, "command": command, "upstream": upstream,
                      "tools": tools or {"executables": {}, "files": {}},
                      "evidence_class": analysis.evidence_class, "logs": logs, "converged": response.get("converged"),
                      "residuals": response.get("residuals", {}), "execution": "complete", "settings": analysis.settings,
                      "seed": analysis.run.seed, "limitations": ["Trusted local execution; undeclared host and external dependencies are not isolated.", *analysis.run.uncontrolled_dependencies]}
            return self.publish(record, slot)
