import json

import pytest

from closure.engine import Engine
from closure.io import ClosureError, file_digest
from closure.reporting import export_report
from conftest import edit_yaml
from test_rfc_acceptance import artifact_analysis, input_power


def test_report_exports_verified_artifacts_without_running_again(project_dir, tmp_path):
    artifact_analysis(project_dir)
    Engine(project_dir).build(trusted=True)
    destination = tmp_path / "export"
    result = export_report(Engine(project_dir), destination)
    assert result["gate"] and result["artifacts"] == 1
    manifest = json.loads((destination / "artifacts.json").read_text())
    artifact = manifest["artifacts"][0]
    assert file_digest(destination / artifact["file"]) == artifact["sha256"]
    report = json.loads((destination / "report.json").read_text())
    assert report["executed"] == []
    assert "Selected scope closed" in (destination / "index.html").read_text()
    assert report["analyses"][0]["record"]["sources"]
    with pytest.raises(ClosureError) as exc:
        export_report(Engine(project_dir), destination)
    assert exc.value.code == "OUTPUT_EXISTS"


def test_stale_report_never_exports_historical_artifacts_as_current(project_dir, tmp_path):
    artifact_analysis(project_dir)
    Engine(project_dir).build(trusted=True)
    input_power(project_dir, 120)
    destination = tmp_path / "stale-export"
    result = export_report(Engine(project_dir), destination)
    assert not result["gate"] and result["artifacts"] == 0
    assert "STALE" in (destination / "index.html").read_text()


def test_report_escapes_project_text(project_dir, tmp_path):
    edit_yaml(project_dir / "project.yaml", lambda d: d.update(name='<script>alert("unsafe")</script>'))
    destination = tmp_path / "escaped"
    export_report(Engine(project_dir), destination)
    page = (destination / "index.html").read_text()
    assert "<script>" not in page
    assert "&lt;script&gt;" in page
