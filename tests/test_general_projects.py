"""Different engineering domains exercise the same compiler and viewer API."""
import json
import shutil
import threading
from pathlib import Path
from urllib.request import Request, urlopen

import pytest
from ruamel.yaml import YAML

from closure.cli import main
from closure.editing import patch_parameters
from closure.engine import Engine, approve_baseline, sweep
from closure.io import ClosureError
from closure.project import Project
from closure.reporting import export_report
from closure.viewer_server import create_server


@pytest.fixture
def service(tmp_path):
    shutil.copytree(Path(__file__).parents[1]/"examples/service", tmp_path,
                    dirs_exist_ok=True, ignore=shutil.ignore_patterns(".closure", "deliverables", "__pycache__"))
    return tmp_path


@pytest.mark.parametrize("output_flags", [[], ["--json"]])
def test_cli_impact_lists_dependencies_without_treating_them_as_a_report(service, capsys, output_flags):
    assert main(["impact", "workload.arrival_rate", "--project", str(service), *output_flags]) == 0
    output = capsys.readouterr().out
    if not output_flags:
        assert "6 downstream elements" in output
        assert "platform.capacity" in output and "platform.energy" not in output
        return
    result = json.loads(output)
    assert result["changed"] == "workload.arrival_rate"
    assert result["requirements"] == ["operations.CAP-001"]
    assert "platform.capacity" in result["affected"]
    assert "platform.energy" not in result["affected"]


def test_service_contexts_change_impact_history_sweep_and_export(service):
    baseline = Engine(service).build(trusted=True)
    assert baseline["gate"]
    assert baseline["context"] == {"scenario": "routine", "configuration": "balanced", "point": "baseline"}
    assert baseline["values"]["platform.capacity.headroom"]["value"] == pytest.approx(100/3)
    assert baseline["values"]["platform.energy.total"]["value"] == 180
    patch_parameters(service, Project(service).source_hash, {"workload.arrival_rate": {"value": 260, "unit": "1/s"}})
    stale = Engine(service, "routine", "balanced").plan()
    assert {a["id"]:a["state"] for a in stale["analyses"]} == {
        "platform.capacity":"stale", "platform.energy":"current"}
    failed = Engine(service, "routine", "balanced").build(trusted=True)
    assert not failed["gate"] and failed["executed"] == ["platform.capacity"]
    explanation = Engine(service, "routine", "balanced").explain("operations.CAP-001")
    assert any(p[0] == "workload.arrival_rate" and "platform.capacity" in p for p in explanation["paths"])
    assert Engine(service, "surge", "expanded").build(trusted=True)["gate"]
    patch_parameters(service, Project(service).source_hash, {"workload.arrival_rate": {"value": 160, "unit": "1/s"}})
    restored = Engine(service, "routine", "balanced").build(trusted=True)
    assert restored["gate"] and restored["executed"] == []
    study = sweep(service, service/"studies/capacity.yaml", trusted=True)
    assert study["complete_evidence"] and study["expected"] == study["completed"] == 6
    assert study["passed"] == study["failed"] == 3
    assert len(study["reports"]) == 6
    output = service/"deliverables/test"
    result = export_report(service, output, report_id=baseline["id"])
    assert (output/"index.html").is_file() and result
    assert export_report(service, service/"deliverables/current")


def test_json_project_round_trip_and_viewer_discovery(service):
    parser = YAML(typ="safe")
    for source in list(service.glob("model/*.yaml")) + [service/"project.yaml"]:
        data = parser.load(source)
        if source.name == "project.yaml":
            data["modules"] = ["model/*.json"]
        source.with_suffix(".json").write_text(json.dumps(data), encoding="utf-8")
        source.unlink()
    assert Project(service).manifest_path.name == "project.json"
    server = create_server(service, port=0, workspace=service.parent, trusted=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    def request(path, body=None):
        req = Request(f"http://127.0.0.1:{server.server_port}"+path,
                      data=json.dumps(body).encode() if body else None,
                      headers={"Content-Type":"application/json", "X-Closure-Token":server.app.token})
        with urlopen(req, timeout=30) as response:
            return json.load(response)
    try:
        snapshot = request("/api/project")
        assert snapshot["project"]["project"] == "service-capacity"
        assert snapshot["report"]["context"]["scenario"] == "routine"
        assert any(p["id"] == "service-capacity" for p in snapshot["projects"])
        request("/api/parameters", {"project":snapshot["path"], "source_hash":snapshot["report"]["source_hash"],
                                    "changes":{"platform.workers":{"value":6}}})
        assert json.loads((service/"model/platform.json").read_text())["parameters"]["workers"]["value"] == 6
        report = request("/api/build", {"project":snapshot["path"],"scenario":"surge","configuration":"expanded"})
        assert report["gate"]
    finally:
        server.shutdown(); server.server_close(); thread.join(5)
    (service/"project.yaml").write_text("schema: closure/0.1\n")
    with pytest.raises(ClosureError, match="Multiple project manifests"):
        Project(service)
    assert Project(service/"project.json").manifest.project == "service-capacity"


def test_init_starts_neutral_and_preserves_existing_work(tmp_path):
    root=tmp_path/"starter"
    assert main(["init","--project",str(root)]) == 0
    project=Project(root)
    assert project.manifest.project == "engineering-project" and list(project.modules) == ["system"]
    assert not Engine(project).build(trusted=True)["gate"]  # initial scope still needs review
    approve_baseline(project,"test reviewer","Review the explicit starter criterion")
    assert Engine(root).build(trusted=True)["gate"]
    power=tmp_path/"power"
    assert main(["init","--project",str(power),"--template","power"]) == 0
    assert Project(power).manifest.project == "power-demo"
    collision=tmp_path/"existing"; (collision/"analysis").mkdir(parents=True)
    existing=collision/"analysis/evaluate.py"; existing.write_text("user-owned work")
    assert main(["init","--project",str(collision)]) == 2
    assert existing.read_text() == "user-owned work"
