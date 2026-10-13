"""Executable mutations with expectations from RFC 0001, T01 through T28."""
import json
import subprocess
from pathlib import Path
import pytest
from hypothesis import given, settings, strategies as st
from closure.editing import patch_parameters
from closure.engine import Engine, approve_baseline, record_review, sweep
from closure.io import ClosureError, atomic_json, digest
from closure.project import Project
from conftest import edit_yaml, runner


def assessment(report):
    return next(a for a in report["requirements"] if a["id"] == "power.PWR-001")


def input_power(path, value, unit="W"):
    edit_yaml(path / "model/payload.yaml", lambda d: d["parameters"]["peak_power"].update(value=value, unit=unit))


def approve(path):
    return approve_baseline(Project(path), "test reviewer", "Reviewed modified fixture scope")


def test_T01_baseline_and_T02_stale_and_T03_explained_failure(project_dir):
    baseline = Engine(project_dir).build(trusted=True)
    assert baseline["gate"]
    assert assessment(baseline)["comparisons"][0]["actual"] == 180
    assert baseline["assumptions"][0]["id"] == "payload.peak_power"
    input_power(project_dir, 120)
    planned = Engine(project_dir).plan()
    assert assessment(planned)["freshness"] == "stale"
    assert assessment(planned)["verdict"] == "unknown"
    assert not planned["gate"]
    built = Engine(project_dir).build(trusted=True)
    assert not built["gate"]
    assert assessment(built)["verdict"] == "fail"
    assert assessment(built)["comparisons"][0]["margin"] == -20
    assert ["payload.peak_power", "power.budget", "power.budget.total", "power.PWR-001"] in Engine(project_dir).explain("power.PWR-001")["paths"]


def test_T04_equivalent_units(project_dir):
    input_power(project_dir, 0.08, "kW")
    result = Engine(project_dir).build(trusted=True)
    assert result["gate"]
    assert assessment(result)["comparisons"][0]["actual"] == 180


def test_T05_incompatible_units_rejected_statically(project_dir):
    input_power(project_dir, 80, "kg")
    with pytest.raises(ClosureError, match="Cannot convert"):
        Project(project_dir)
    assert not (project_dir / ".closure/runs").exists()


def test_T06_transitive_python_import_invalidates(project_dir):
    helper = project_dir / "analysis/helper.py"
    helper.write_text("OFFSET = 0\n")
    script = project_dir / "analysis/power_budget.py"
    script.write_text("from helper import OFFSET\n" + script.read_text().replace('total = ', 'total = OFFSET + '))
    edit_yaml(project_dir / "model/power.yaml", lambda d: d["analyses"]["budget"]["run"].update(sources=["analysis/power_budget.py"]))
    assert Engine(project_dir).build(trusted=True)["gate"]
    helper.write_text("OFFSET = 1\n")
    assert assessment(Engine(project_dir).plan())["freshness"] == "stale"


def test_T07_unrelated_change_reuses_analysis(project_dir):
    baseline = Engine(project_dir).build(trusted=True)
    (project_dir / "model/unrelated.yaml").write_text("schema: closure/0.1\nmodule: unrelated\nowner: Other team\nparameters:\n  count: {value: 12}\n")
    result = Engine(project_dir).build(trusted=True)
    assert result["gate"]
    assert result["source_hash"] != baseline["source_hash"]
    assert not result["executed"]
    assert result["analyses"][0]["record"]["id"] == baseline["analyses"][0]["record"]["id"]


def artifact_analysis(path):
    runner(path, "p = pathlib.Path(r['output_dir']) / 'shape.stl'\np.write_text('engineering artifact')\njson.dump({'protocol':'closure-run/0.1', 'invocation_id':r['invocation_id'], 'outputs':{'total':{'value':180,'unit':'W'}, 'shape':{'path':str(p)}}}, sys.stdout)",
           {"total": {"type": "quantity", "unit": "W"}, "shape": {"type": "artifact"}})


def test_T08_missing_or_corrupt_artifact_prevents_reuse(project_dir):
    artifact_analysis(project_dir)
    result = Engine(project_dir).build(trusted=True)
    assert result["gate"]
    artifact = Path(result["values"]["power.budget.shape"]["path"])
    artifact.write_text("modified after build")
    assert assessment(Engine(project_dir).plan())["freshness"] == "missing"
    artifact.unlink()
    assert not Engine(project_dir).plan()["gate"]


def test_T09_crash_does_not_publish_partial_evidence(project_dir):
    Engine(project_dir).build(trusted=True)
    runner(project_dir, "pathlib.Path(r['output_dir'], 'leftover.json').write_text('180')\nraise RuntimeError('intentional failure')")
    result = Engine(project_dir).build(trusted=True)
    assert not result["gate"]
    assert assessment(result)["execution"] == "error"
    assert len(list((project_dir / ".closure/runs").glob("*.json"))) == 1


@pytest.mark.parametrize("output,invocation", [
    ("{'value':float('nan'),'unit':'W'}", "r['invocation_id']"),
    ("{'value':float('inf'),'unit':'W'}", "r['invocation_id']"),
    ("{'value':180,'unit':'kg'}", "r['invocation_id']"),
    ("{'value':[180],'unit':'W'}", "r['invocation_id']"),
    ("{'value':180,'unit':'W'}", "'wrong-invocation'"),
])
def test_T10_bad_runner_output_rejected(project_dir, output, invocation):
    runner(project_dir, f"json.dump({{'protocol':'closure-run/0.1','invocation_id':{invocation},'outputs':{{'total':{output}}}}},sys.stdout)")
    result = Engine(project_dir).build(trusted=True)
    assert not result["gate"]
    assert assessment(result)["execution"] == "error"
    assert not list((project_dir / ".closure/runs").glob("*.json"))


def test_T11_semantic_qualifiers_checked(project_dir):
    edit_yaml(project_dir / "model/payload.yaml", lambda d: d["parameters"]["peak_power"].update(qualifiers={"aggregation": "peak"}))
    edit_yaml(project_dir / "model/power.yaml", lambda d: d["analyses"]["budget"]["inputs"]["payload"].update(qualifiers={"aggregation": "average"}))
    with pytest.raises(ClosureError) as failure:
        Project(project_dir)
    assert failure.value.code == "QUALIFIER_MISMATCH"


def test_T12_module_move_preserves_identity_and_cache(project_dir):
    before = Engine(project_dir).build(trusted=True)
    (project_dir / "model/payload.yaml").rename(project_dir / "model/supplier.yaml")
    after = Engine(project_dir).build(trusted=True)
    assert after["gate"] and not after["executed"]
    assert before["values"] == after["values"]


def test_T13_duplicate_producer_symbols_rejected(project_dir):
    (project_dir / "model/duplicate.yaml").write_bytes((project_dir / "model/power.yaml").read_bytes())
    with pytest.raises(ClosureError) as failure:
        Project(project_dir)
    assert failure.value.code == "DUPLICATE_ID"


def test_T14_four_sweep_points_keep_distinct_evidence(project_dir):
    result = sweep(project_dir, "studies/payload_power.yaml", trusted=True)
    assert (result["expected"], result["passed"], result["failed"]) == (4, 2, 2)
    assert result["complete_evidence"]
    assert sorted(assessment(r)["comparisons"][0]["actual"] for r in result["reports"]) == [170, 180, 210, 220]
    assert len({r["context"]["point"] for r in result["reports"]}) == 4
    assert len({r["analyses"][0]["record"]["id"] for r in result["reports"]}) == 4


def test_T15_failed_sweep_point_stays_in_denominator(project_dir):
    script = project_dir / "analysis/power_budget.py"
    script.write_text(script.read_text().replace('total = ', "if request['inputs']['payload']['value'] == 120 and request['inputs']['base']['value'] == 100: raise RuntimeError('point fails')\ntotal = "))
    result = sweep(project_dir, "studies/payload_power.yaml", trusted=True)
    assert result["expected"] == result["completed"] == 4
    assert not result["complete_evidence"]
    assert result["passed"] == 2 and result["failed"] == 2
    assert sum(assessment(r)["execution"] == "error" for r in result["reports"]) == 1


def test_T16_wrong_context_evidence_rejected(project_dir):
    report = Engine(project_dir).build(trusted=True)
    record = report["analyses"][0]["record"]
    record["context"]["scenario"] = "hot"
    record.pop("record_hash")
    record["record_hash"] = digest(record)
    atomic_json(project_dir / ".closure/runs" / f"{record['id']}.json", record)
    planned = Engine(project_dir).plan()
    assert not planned["gate"]
    assert assessment(planned)["freshness"] == "missing"


def test_T17_invalid_model_domain_never_vacuously_passes(project_dir):
    edit_yaml(project_dir / "model/power.yaml", lambda d: d["analyses"]["budget"].update(valid_when=[{"actual": {"ref": "payload.peak_power"}, "op": "lt", "limit": {"value": 50, "unit": "W"}}]))
    result = Engine(project_dir).build(trusted=True)
    assert assessment(result)["verdict"] == "unknown"
    assert assessment(result)["execution"] == "blocked"
    assert result["analyses"][0]["error"]["code"] == "INVALID_DOMAIN"


def test_T18_requirement_text_change_requires_review_not_rerun(project_dir):
    Engine(project_dir).build(trusted=True)
    edit_yaml(project_dir / "model/power.yaml", lambda d: d["requirements"]["PWR-001"].update(text="Revised requirement meaning"))
    result = Engine(project_dir).build(trusted=True)
    assert assessment(result)["freshness"] == "current"
    assert assessment(result)["acceptance"] == "review_required"
    assert not result["gate"] and not result["executed"]


def test_T19_children_do_not_verify_parent(project_dir):
    edit_yaml(project_dir / "model/power.yaml", lambda d: d["requirements"].update({"SYSTEM": {"text": "Integrated behavior shall be verified."}}))
    edit_yaml(project_dir / "model/power.yaml", lambda d: d["requirements"]["PWR-001"].update(derived_from=["power.SYSTEM"]))
    approve(project_dir)
    result = Engine(project_dir).build(trusted=True)
    assert assessment(result)["closed"]
    assert next(a for a in result["requirements"] if a["id"] == "power.SYSTEM")["verdict"] == "unknown"
    assert not result["gate"]


def test_T20_weakening_or_deleting_obligation_cannot_silently_pass(project_dir):
    input_power(project_dir, 120)
    Engine(project_dir).build(trusted=True)
    edit_yaml(project_dir / "model/power.yaml", lambda d: d["requirements"]["PWR-001"]["verify"]["limit"].update(value=1000))
    result = Engine(project_dir).plan()
    assert assessment(result)["verdict"] == "pass"
    assert not result["gate"] and result["baseline"]["status"] == "changed"
    edit_yaml(project_dir / "model/power.yaml", lambda d: d.update(requirements={}))
    assert not Engine(project_dir).plan()["gate"]


@pytest.mark.parametrize("malicious", [
    "unsafe: !!python/object/apply:os.system ['echo unsafe']\n",
    "one: &a 3\ntwo: *a\n", "one: 1\none: 2\n", "one: {<<: {thing: 2}}\n",
    "one: .nan\n", "one: .inf\n", "? [one, two]\n: 1\n",
])
def test_T21_unsafe_yaml_rejected_without_execution(project_dir, malicious, monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("source must not launch processes"))
    (project_dir / "model/unsafe.yaml").write_text(malicious)
    with pytest.raises(ClosureError):
        Project(project_dir)


def test_T22_check_never_runs_analysis_or_imports_project_code(project_dir, monkeypatch):
    runner(project_dir, "raise RuntimeError('must never run')")
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("check launched a process"))
    assert Project(project_dir).check()["valid"]
    assert not (project_dir / ".closure/runs").exists()


def test_T23_cycle_diagnostic_has_source_location(project_dir):
    edit_yaml(project_dir / "model/power.yaml", lambda d: d["analyses"]["budget"]["inputs"]["base"].update(ref="power.budget.total"))
    with pytest.raises(ClosureError) as failure:
        Project(project_dir)
    assert failure.value.code == "COMPUTE_CYCLE"
    assert "power.yaml:" in failure.value.location


def test_T24_nonconvergence_is_not_evidence(project_dir):
    edit_yaml(project_dir / "model/power.yaml", lambda d: d["analyses"]["budget"].update(solver=True))
    runner(project_dir, "json.dump({'protocol':'closure-run/0.1','invocation_id':r['invocation_id'],'converged':False,'outputs':{'total':{'value':180,'unit':'W'}}},sys.stdout)")
    result = Engine(project_dir).build(trusted=True)
    assert not result["gate"]
    assert assessment(result)["execution"] == "error"


def test_T25_optimistic_patch_rejects_second_writer(project_dir):
    original = Project(project_dir).source_hash
    patch_parameters(project_dir, original, {"payload.peak_power": {"value": 81, "unit": "W"}})
    with pytest.raises(ClosureError) as failure:
        patch_parameters(project_dir, original, {"payload.peak_power": {"value": 82, "unit": "W"}})
    assert failure.value.code == "SOURCE_CONFLICT"
    assert Project(project_dir).parameters["payload.peak_power"].value == 81


def test_T26_uncontrolled_dependencies_disable_reuse(project_dir):
    edit_yaml(project_dir / "model/power.yaml", lambda d: d["analyses"]["budget"]["run"].update(uncontrolled_dependencies=["live weather service"]))
    first = Engine(project_dir).build(trusted=True)
    assert first["gate"]
    assert not Engine(project_dir).plan()["gate"]
    second = Engine(project_dir).build(trusted=True)
    assert second["analyses"][0]["record"]["id"] != first["analyses"][0]["record"]["id"]


def test_T27_empty_scope_cannot_approve_or_close(project_dir):
    edit_yaml(project_dir / "project.yaml", lambda d: d.update(scope=[]))
    assert not Engine(project_dir).build(trusted=True)["gate"]
    with pytest.raises(ClosureError) as failure:
        approve(project_dir)
    assert failure.value.code == "EMPTY_SCOPE"


def test_T28_waiver_is_distinct_from_verification(project_dir):
    edit_yaml(project_dir / "project.yaml", lambda d: d["policy"].update(allow_waivers=True))
    approve(project_dir)
    input_power(project_dir, 120)
    Engine(project_dir).build(trusted=True)
    record_review(Engine(project_dir), "power.PWR-001", "waived", "independent reviewer", "Explicit concept exception")
    result = Engine(project_dir).plan()
    assert result["gate"]
    assert assessment(result)["status"] == "WAIVED"
    assert assessment(result)["verdict"] == "fail"
    assert not assessment(result)["closed"]


@given(st.floats(min_value=100.01, max_value=1e6, allow_nan=False, allow_infinity=False))
@settings(max_examples=20, deadline=None)
def test_requirement_comparison_property(value):
    # Direct independent expectation for the documented power inequality.
    from closure.models import Criterion
    engine = object.__new__(Engine)
    engine.values = {"p.total": {"value": value + 100, "unit": "W"}}
    criterion = Criterion.model_validate({"actual": {"ref": "p.total"}, "op": "lte", "limit": {"value": 200, "unit": "W"}})
    result = engine._criterion(criterion)
    assert result["verdict"] == "fail" and result["margin"] < 0
