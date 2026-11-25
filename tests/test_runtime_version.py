import pytest

from closure.engine import Engine, approve_baseline, sweep
from closure.io import ClosureError, atomic_json, digest, file_digest, read_json
from closure.reporting import export_report
from conftest import edit_yaml, runner
from test_rfc_acceptance import artifact_analysis


def test_live_runner_and_approvals_require_02(project_dir):
    baseline_path = project_dir / "reviews/baseline.json"
    previous = {**read_json(baseline_path), "schema": "closure-baseline/0.1"}
    atomic_json(baseline_path, previous)
    runner(project_dir, """assert r["protocol"] == "closure-run/0.2"
json.dump({"protocol": r["protocol"], "invocation_id": r["invocation_id"],
           "outputs": {"total": {"value": 180, "unit": "W"}}}, sys.stdout)""")
    engine = Engine(project_dir)
    built = engine.verify(trusted=True)
    assert built["schema"] == "closure-report/0.2"
    assert built["analyses"][0]["record"]["protocol"] == "closure-evidence/0.2"
    assert not built["gate"] and built["baseline"]["status"] == "changed"
    assert built["baseline"]["approved_hash"] == built["baseline"]["current_hash"]
    assert "closure approve-baseline" in built["baseline"]["message"]
    assert read_json(baseline_path) == previous
    current = approve_baseline(project_dir, "Power reviewer", "Reviewed the 0.2 power budget")
    assert current["schema"] == "closure-baseline/0.2" and engine.plan()["gate"]

    runner(project_dir, """assert r["protocol"] == "closure-run/0.2"
json.dump({"protocol": "closure-run/0.1", "invocation_id": r["invocation_id"],
           "outputs": {"total": {"value": 180, "unit": "W"}}}, sys.stdout)""")
    result = Engine(project_dir).verify(trusted=True)
    error = result["analyses"][0]["error"]
    assert error["code"] == "OUTPUT_INVALID" and "closure-run/0.2" in error["message"]
    assert not result["gate"] and result["analyses"][0]["record"] is None
    assert len(engine.store.history()["runs"]) == 1


def test_studies_require_current_source_and_write_current_results(project_dir):
    relative = "studies/payload_power.yaml"
    path = project_dir / relative
    edit_yaml(path, lambda study: study.update(schema="closure/0.1", grid={"power.base_load": [{"value": 90, "unit": "W"}]}))
    with pytest.raises(ClosureError) as error:
        sweep(project_dir, relative, trusted=True)
    assert error.value.code == "SOURCE_VERSION" and error.value.location == str(path)
    assert not list((project_dir / ".closure/runs").glob("*.json"))
    edit_yaml(path, lambda study: study.update(schema="closure/0.2"))
    result = sweep(project_dir, relative, trusted=True)
    assert result["schema"] == "closure-study/0.2" and result["passed"] == 1
    assert result["reports"][0]["schema"] == "closure-report/0.2"


def test_sealed_01_run_and_report_remain_inspectable_and_exportable(project_dir):
    artifact_analysis(project_dir)
    engine = Engine(project_dir)
    report = engine.verify(trusted=True)
    store = engine.store
    # Build the earlier standalone snapshot shape, including a retained input/output artifact.
    report["schema"] = "closure-report/0.1"
    report["model"]["project"].pop("kind")
    report["model"]["project"]["schema"] = "closure/0.1"
    for module in report["model"]["modules"]:
        module["schema"] = "closure/0.1"
    run = report["analyses"][0]["record"]
    run["protocol"] = "closure-evidence/0.1"
    del run["record_hash"], report["report_hash"]
    run["record_hash"] = digest(run)
    report["report_hash"] = digest(report)
    run_path = store.root / "runs" / f"{run['id']}.json"
    report_path = store.root / "reports" / f"{report['id']}.json"
    atomic_json(run_path, run)
    atomic_json(report_path, report)
    original = run_path.read_bytes(), report_path.read_bytes()

    # Even a matching cache key cannot turn a historical record into current support.
    assert engine.plan()["analyses"][0]["record"] is None
    assert store.load_run(run["id"]) == run and store.load_report(report["id"]) == report
    destination = project_dir / "export"
    export_report(project_dir, destination, report["id"])
    assert (destination / "report.json").read_bytes() == original[1]
    exported = read_json(destination / "artifacts.json")
    assert exported["schema"] == "closure-export/0.2" and exported["report_hash"] == report["report_hash"]
    artifact, = exported["artifacts"]
    assert file_digest(destination / artifact["file"]) == artifact["sha256"] == run["outputs"]["shape"]["sha256"]
    assert (run_path.read_bytes(), report_path.read_bytes()) == original
