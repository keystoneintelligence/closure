import sys
import pytest

from closure.engine import Engine
from closure.io import file_digest
from conftest import edit_yaml, runner


def tool_contract(project_dir, tools=None, tool_files=None):
    edit_yaml(project_dir / "model/power.yaml", lambda d: d["analyses"]["budget"]["run"].update(
        tools=tools or {}, tool_files=tool_files or []))


def test_external_tool_identity_reaches_runner_and_evidence(project_dir):
    tool_contract(project_dir, {"simulator": "python"})
    runner(project_dir, "assert r['tools']['executables']['simulator']['sha256']\n"
           "json.dump({'protocol':'closure-run/0.1','invocation_id':r['invocation_id'],'outputs':{'total':{'value':180,'unit':'W'}}},sys.stdout)")
    report = Engine(project_dir).build(trusted=True)
    assert report["gate"]
    record = report["analyses"][0]["record"]
    assert record["tools"]["executables"]["simulator"]["sha256"] == file_digest(sys.executable)
    assert Engine(project_dir).build(trusted=True)["executed"] == []


def test_declared_tool_file_change_invalidates_evidence_without_a_probe(project_dir, monkeypatch):
    dependency = project_dir / "solver-runtime.lock"
    dependency.write_text("version one")
    tool_contract(project_dir, {"simulator": "python"}, ["solver-runtime.lock"])
    assert Engine(project_dir).build(trusted=True)["gate"]
    dependency.write_text("version two")
    def forbidden(*args, **kwargs):
        raise AssertionError("Planning must not execute tool probes")
    monkeypatch.setattr("subprocess.Popen", forbidden)
    result = Engine(project_dir).plan()
    assert result["analyses"][0]["state"] == "stale"
    assert not result["gate"]


def test_local_tool_override_and_missing_tool_are_explicit(project_dir, monkeypatch):
    tool_contract(project_dir, {"simulator": "unavailable-closure-tool-12345"})
    missing = Engine(project_dir).plan()
    assert missing["analyses"][0]["error"]["code"] == "EXECUTABLE_MISSING"
    monkeypatch.setenv("CLOSURE_TOOL_SIMULATOR", sys.executable)
    assert Engine(project_dir).build(trusted=True)["gate"]


def test_tool_mutation_during_run_cannot_publish_evidence(project_dir):
    dependency = project_dir / "runtime.bin"
    dependency.write_bytes(b"before")
    tool_contract(project_dir, tool_files=["runtime.bin"])
    runner(project_dir, f"pathlib.Path({str(dependency)!r}).write_bytes(b'after')\n"
           "json.dump({'protocol':'closure-run/0.1','invocation_id':r['invocation_id'],'outputs':{'total':{'value':180,'unit':'W'}}},sys.stdout)")
    result = Engine(project_dir).build(trusted=True)
    assert result["analyses"][0]["error"]["code"] == "TOOL_MUTATION"
    assert not result["gate"] and not (project_dir / ".closure/runs").exists()
def test_python_runner_retains_the_active_virtual_environment(project_dir):
    runner(project_dir, "import pydantic\n"
           f"assert sys.prefix == {sys.prefix!r}, (sys.prefix, sys.executable)\n"
           "json.dump({'protocol':r['protocol'],'invocation_id':r['invocation_id'],"
           "'outputs':{'total':{'value':180,'unit':'W'}}},sys.stdout)")
    report = Engine(project_dir).build(trusted=True)
    assert report['gate'], [(a['id'], a.get('error')) for a in report['analyses']]


