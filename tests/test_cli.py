"""Exercise the user-facing workflow and shell contracts, not just the parser."""
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from closure.cli import main
from closure.cli_args import COMMANDS
from closure.cli_completion import candidates, SCRIPTS
from closure.engine import Engine
from closure.project import Project
from conftest import edit_yaml, runner
from test_general_projects import service
from test_verification_alternatives import alternatives


def test_help_describes_commands_and_examples_without_needing_a_project(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main([]) == 0
    output = capsys.readouterr().out
    assert "Everyday workflow" in output and "nearest enclosing project" in " ".join(output.split())
    for name in COMMANDS:
        assert main(["help", name]) == 0
        output = capsys.readouterr().out
        assert "Examples:" in output and f"closure {name}" in output
    with pytest.raises(SystemExit) as stopped:
        main(["--version"])
    assert stopped.value.code == 0
    assert capsys.readouterr().out.startswith("closure 0.")


def test_discovery_from_subdirectory_explicit_selection_and_init(service, tmp_path, monkeypatch, capsys):
    nested = service / "analysis" / "nested"
    nested.mkdir()
    monkeypatch.chdir(nested)
    assert main(["check", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["project"] == "service-capacity"
    assert main(["check", "-p", str(service / "project.yaml")]) == 0
    assert "VALID" in capsys.readouterr().out
    assert main(["check", "-p", str(nested)]) == 2  # Explicit paths never fall back to a parent.
    assert capsys.readouterr().err
    assert main(["init"]) == 0
    assert Project(nested).manifest.project == "engineering-project"


def test_set_verify_explain_restore_and_verbose_human_workflow(service, monkeypatch, capsys):
    monkeypatch.chdir(service / "model")
    assert main(["verify", "--trusted"]) == 0
    output = capsys.readouterr()
    assert "[1/2] RUN" in output.err and "DONE" in output.err
    assert "2 ran, 0 reused" in output.out and "Saved:" in output.out
    original = Project(service).parameters["workload.arrival_rate"].model_dump()
    assert main(["set", "workload.arrival_rate", "250"]) == 0
    output = capsys.readouterr()
    assert "160 1/s -> 250 1/s" in output.out and "6 downstream elements" in output.out
    updated = Project(service).parameters["workload.arrival_rate"].model_dump()
    assert updated == {**original, "value": 250}
    assert main(["plan"]) == 0
    output = capsys.readouterr()
    assert "WILL RUN     platform.capacity (stale)" in output.out
    assert "CACHED       platform.energy" in output.out
    assert "No analyses executed" in output.out and output.err == ""
    assert main(["verify", "--trusted"]) == 1
    output = capsys.readouterr()
    assert "1 ran, 1 reused" in output.out and "FAIL" in output.out
    assert "CACHED  platform.energy" in output.err
    assert main(["explain", "operations.CAP-001"]) == 0
    output = capsys.readouterr().out
    assert "required >= 20 percent" in output and "margin -24.1667" in output
    assert "workload.arrival_rate -> platform.capacity -> platform.capacity.headroom -> operations.CAP-001" in output
    assert main(["set", "workload.arrival_rate", "160"]) == 0
    capsys.readouterr()
    assert main(["verify", "--trusted", "--verbose"]) == 0
    output = capsys.readouterr()
    assert "0 ran, 2 reused" in output.out and "inputs:" in output.out and "Run:" in output.out


@pytest.mark.parametrize("flags", [["--json"], ["--quiet"], ["--quiet", "--json"]])
def test_structured_and_quiet_verification_keep_streams_clean(service, capsys, flags):
    assert main(["verify", "-p", str(service), "--trusted", *flags]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    if "--json" in flags:
        report = json.loads(output.out)
        assert report["gate"] and report["executed"] == ["platform.capacity", "platform.energy"]
    else:
        assert output.out == ""


@pytest.mark.parametrize("arguments", [["set", "workload.arrival_rate", "nan"], ["set", "workload.arrival_rate", "inf"],
    ["set", "workload.arrival_rate", "true"], ["set", "workload.arrival_rate", "10", "--unit", "kg"],
    ["set", "workload.arrival_rate", "10", "--expected-hash", "outdated"], ["set", "no.such.input", "10"],
    ["set", "workload.arrival_rate", "10", "--scenario", "surge"]])
def test_rejected_set_never_changes_source(service, capsys, arguments):
    before = {p: p.read_bytes() for p in Project(service).source_files}
    assert main([*arguments, "-p", str(service)]) == 2
    output = capsys.readouterr()
    assert output.out == "" and "error[" in output.err and "Traceback" not in output.err
    assert all(p.read_bytes() == content for p, content in before.items())


def test_set_units_reason_context_overrides_and_limits(service, capsys):
    assert main(["set", "workload.arrival_rate", "9600", "--unit", "1/min", "--reason", "Measured", "-p", str(service), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["after"]["rationale"] == "Measured" and result["after"]["origin"] == "assumption"
    assert result["after"]["unit"] == "1/min" and not result["obligation_change"]
    assert Engine(service, "surge", "balanced").parameters["workload.arrival_rate"].value == 260
    assert main(["set", "operations.minimum_headroom", "25", "-p", str(service)]) == 0
    assert "baseline needs review" in capsys.readouterr().out
    assert Engine(service).baseline()["status"] == "changed"


def test_negative_scientific_input_and_missing_project_diagnostics(service, tmp_path, monkeypatch, capsys):
    assert main(["set", "workload.arrival_rate", "-1e2", "-p", str(service), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["after"]["value"] == -100
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.mkdir()
    monkeypatch.chdir(outside)
    assert main(["check"]) == 2
    assert "Use -p PATH" in capsys.readouterr().err
    assert candidates(["set", "work"]) == []


def test_set_handles_boolean_literal_text_enum_artifact_and_json_sources(service, capsys):
    def add_inputs(document):
        document["parameters"].update(enabled={"value": True}, label={"value": "original"},
                                      mode={"value": "slow", "type": "enum", "choices": ["slow", "fast"]},
                                      source={"path": "analysis/capacity.py"})
    edit_yaml(service / "model/workload.yaml", add_inputs)
    from ruamel.yaml import YAML
    path = service / "model/workload.yaml"
    path.with_suffix(".json").write_text(json.dumps(YAML(typ="safe").load(path)), encoding="utf-8")
    path.unlink()
    edit_yaml(service / "project.yaml", lambda d: d["modules"].append("model/*.json"))
    for identifier, value in [("enabled", "false"), ("label", "true"), ("mode", "fast"), ("source", "analysis/energy.py")]:
        assert main(["set", "workload." + identifier, value, "-p", str(service)]) == 0
    parameters = Project(service).parameters
    assert parameters["workload.enabled"].value is False
    assert parameters["workload.label"].value == "true"
    assert parameters["workload.mode"].value == "fast"
    assert parameters["workload.source"].path == "analysis/energy.py"
    json.loads(path.with_suffix(".json").read_text())
    for arguments in [["workload.enabled", "yes"], ["workload.mode", "unknown"], ["workload.label", "hello", "--unit", "W"]]:
        assert main(["set", *arguments, "-p", str(service)]) == 2


def test_patch_file_stdin_validation_and_compare_and_swap(service, monkeypatch, capsys):
    initial = Project(service).source_hash
    changes = {"workload.arrival_rate": {"value": 240, "unit": "1/s"}}
    path = service / "changes.json"
    path.write_text(json.dumps(changes), encoding="utf-8")
    assert main(["patch", "-p", str(service), "--expected-hash", initial, "--changes-file", str(path)]) == 0
    assert main(["patch", "-p", str(service), "--expected-hash", initial, "--changes-file", str(path)]) == 2
    for value, expected in [("[]", 2), ("{}", 2), ('{"workload.arrival_rate":null}', 2), ("bad json", 2), (json.dumps(changes), 0)]:
        monkeypatch.setattr(sys, "stdin", io.StringIO(value))
        assert main(["patch", "-p", str(service), "--expected-hash", Project(service).source_hash, "--changes-file", "-"]) == expected


def test_errors_are_actionable_and_json_usage_errors_are_parseable(service, capsys):
    assert main(["inspect", "workload.arrival_rat", "-p", str(service)]) == 2
    assert "Did you mean: workload.arrival_rate" in capsys.readouterr().err
    assert main(["plan", "--scenario", "nonesuch", "-p", str(service)]) == 2
    assert "Scenarios: routine, surge" in capsys.readouterr().err
    for argv in [["set", "--json"], ["vrefiy", "--json"], ["verify", "--json", "--unknown"]]:
        assert main(argv) == 2
        output = capsys.readouterr()
        assert json.loads(output.out)["error"]["code"] == "USAGE_ERROR" and output.err == ""


def test_alternative_support_is_distinguished_in_human_output(alternatives, capsys):
    (alternatives / "analysis/alternate.py").unlink()
    assert main(["verify", "--trusted", "-p", str(alternatives)]) == 0
    output = capsys.readouterr().out
    assert "Any one alternative" in output
    assert "Alternative 1: PASS (selected)" in output and "Alternative 2: UNKNOWN" in output


def test_empty_expected_hash_is_rejected_and_validation_errors_are_concise(service, capsys):
    before = Project(service).source_hash
    assert main(["set", "workload.arrival_rate", "250", "--expected-hash", "", "-p", str(service)]) == 2
    assert Project(service).source_hash == before
    capsys.readouterr()
    edit_yaml(service / "model/workload.yaml", lambda d: d["parameters"].update(mode={"type": "enum", "choices": ["a", "b"], "value": "a"}))
    assert main(["set", "workload.mode", "c", "-p", str(service)]) == 2
    error = capsys.readouterr().err
    assert "enum choice" in error and "https://" not in error and len(error.splitlines()) == 1


def test_progress_announces_execution_before_launch_and_force_does_not_claim_reuse(project_dir):
    engine = Engine(project_dir)
    events = []
    execute = engine.store.execute
    def checked_execute(*args, **kwargs):
        assert events[-1]["event"] == "running"
        return execute(*args, **kwargs)
    engine.store.execute = checked_execute
    assert engine.verify(trusted=True, progress=events.append)["gate"]
    assert [e["event"] for e in events] == ["running", "completed"]
    events.clear()
    Engine(project_dir).verify(trusted=True, progress=events.append)
    assert [e["event"] for e in events] == ["cached"]
    events.clear()
    Engine(project_dir).verify(trusted=True, force=True, progress=events.append)
    assert [e["event"] for e in events] == ["running", "completed"]
    assert events[0]["reason"] == "forced"


def test_quiet_still_reports_execution_errors_and_interrupts(project_dir, monkeypatch, capsys):
    runner(project_dir, "raise RuntimeError('intentional failure')")
    assert main(["verify", "--trusted", "--quiet", "-p", str(project_dir)]) == 1
    output = capsys.readouterr()
    assert output.out == "" and "error[" in output.err
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt()
    monkeypatch.setattr(Engine, "verify", interrupted)
    assert main(["verify", "--trusted", "-p", str(project_dir), "--json"]) == 130
    output = capsys.readouterr()
    assert json.loads(output.out)["error"]["code"] == "INTERRUPTED" and output.err == ""


def test_completion_suggests_symbols_contexts_options_without_execution(service, monkeypatch):
    monkeypatch.chdir(service / "model")
    monkeypatch.setattr(Engine, "build", lambda *a, **kw: pytest.fail("completion executed analyses"))
    assert candidates(["ver"]) == ["verify"]
    assert candidates(["set", "work"]) == ["workload.arrival_rate"]
    assert candidates(["explain", "operations.CAP"]) == ["operations.CAP-001"]
    assert candidates(["verify", "--scenario", "s"]) == ["surge"]
    assert candidates(["verify", "--f"]) == ["--force"]
    assert candidates(["-p", str(service), "verify", "--configuration", "e"]) == ["expanded"]
    assert candidates(["init", "--template", "p"]) == ["power"]
    assert candidates(["verify", "--project", ""]) == []


def test_subprocess_exit_codes_and_stdout_stderr(service):
    def run(*arguments):
        return subprocess.run([sys.executable, "-m", "closure", *arguments, "-p", str(service)], capture_output=True, text=True)
    trust = run("verify")
    assert trust.returncode == 2 and not trust.stdout and "TRUST_REQUIRED" in trust.stderr
    failure = run("verify", "--trusted", "--scenario", "surge", "--json")
    assert failure.returncode == 1 and not failure.stderr and not json.loads(failure.stdout)["gate"]
    passed = run("verify", "--trusted", "--quiet")
    assert passed.returncode == 0 and not passed.stdout and not passed.stderr


@pytest.mark.parametrize("shell", ["powershell", "bash"])
def test_real_shell_completion(service, shell):
    executable = shutil.which("pwsh" if shell == "powershell" else "bash")
    if not executable or (shell == "bash" and os.name == "nt"):
        pytest.skip(f"Native {shell} unavailable")
    script = service / ("completion.ps1" if shell == "powershell" else "completion.bash")
    script.write_text(SCRIPTS[shell], encoding="utf-8")
    env = {**os.environ, "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"]}
    if shell == "powershell":
        command = ". '" + str(script).replace("'", "''") + "'; $line = 'closure set work'; [System.Management.Automation.CommandCompletion]::CompleteInput($line, $line.Length, $null).CompletionMatches | ForEach-Object { $_.CompletionText }"
        argv = [executable, "-NoProfile", "-NonInteractive", "-Command", command]
    else:
        import shlex
        command = f"source {shlex.quote(str(script))}; COMP_WORDS=(closure set work); COMP_CWORD=2; _closure_complete; printf '%s\\n' \"${{COMPREPLY[@]}}\""
        argv = [executable, "-c", command]
    result = subprocess.run(argv, cwd=service, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0 and "workload.arrival_rate" in result.stdout and not result.stderr
