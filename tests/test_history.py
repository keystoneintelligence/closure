"""Historical support must survive edits without being mistaken for current support."""
import json
import shutil

import pytest

from closure.cli import main
from closure.engine import Engine
from closure.evidence import EvidenceStore
from closure.io import ClosureError, atomic_json, file_digest
from closure.reporting import explain_saved_report, export_report
from conftest import edit_yaml, runner
from test_rfc_acceptance import artifact_analysis, input_power


def test_historical_model_and_assessment_survive_source_edits(project_dir, tmp_path, monkeypatch):
    artifact_analysis(project_dir)
    built = Engine(project_dir).build(trusted=True)
    input_power(project_dir, 120)
    assert not Engine(project_dir).plan()["gate"]
    # Inspection/export cannot execute the current source, even if it is now invalid.
    (project_dir / "model/power.yaml").write_text("invalid: [")
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: pytest.fail("History executed project code"))
    store = EvidenceStore(project_dir)
    saved = store.load_report(built["id"])
    assert saved == built and saved["gate"]
    module = next(m for m in saved["model"]["modules"] if m["module"] == "payload")
    assert module["parameters"]["peak_power"]["value"] == 80
    explanation = explain_saved_report(saved, "power.PWR-001")
    assert explanation["requirement"]["comparisons"][0]["actual"] == 180
    assert ["payload.peak_power", "power.budget", "power.budget.total", "power.PWR-001"] in explanation["paths"]
    result = export_report(project_dir, tmp_path / "snapshot", built["id"])
    assert result["mode"] == "historical" and result["artifacts"] == 1
    page = (tmp_path / "snapshot/index.html").read_text(encoding="utf-8")
    assert "Historical build snapshot" in page and "Recorded scope closed" in page
    assert main(["history", "--project", str(project_dir), "--report", built["id"], "--json"]) == 0


def test_uncontrolled_tools_have_inspectable_history_but_no_current_cache(project_dir, tmp_path):
    artifact_analysis(project_dir)
    edit_yaml(project_dir / "model/power.yaml", lambda d: d["analyses"]["budget"]["run"].update(
        uncontrolled_dependencies=["An external simulation runtime is not isolated."]))
    built = Engine(project_dir).build(trusted=True)
    assert built["gate"]
    assert not Engine(project_dir).plan()["gate"]
    exported = export_report(project_dir, tmp_path / "saved-tool-result", built["id"])
    assert exported["gate"] and exported["artifacts"] == 1
    assert EvidenceStore(project_dir).history()["reports"][0]["integrity"] == "verified"


@pytest.mark.parametrize("damage", ["report", "record", "blob", "missing_blob"])
def test_corrupt_history_cannot_be_published_as_verified(project_dir, tmp_path, damage):
    artifact_analysis(project_dir)
    built = Engine(project_dir).build(trusted=True)
    store = EvidenceStore(project_dir)
    if damage == "report":
        built["gate"] = False
        atomic_json(store.root / "reports" / f"{built['id']}.json", built)
        operation = lambda: store.load_report(built["id"])
    elif damage == "record":
        record = built["analyses"][0]["record"]
        record["outputs"]["total"]["value"] = 1
        atomic_json(store.root / "runs" / f"{record['id']}.json", record)
        operation = lambda: store.load_run(record["id"])
    else:
        output = next(v for v in built["analyses"][0]["record"]["outputs"].values() if v["type"] == "artifact")
        blob = store.artifact_path(output)
        if damage == "blob":
            blob.write_bytes(b"changed")
        else:
            blob.unlink()
        operation = lambda: export_report(project_dir, tmp_path / "bad-export", built["id"])
    with pytest.raises(ClosureError) as exc:
        operation()
    assert exc.value.code in ("HISTORY_CORRUPT", "ARTIFACT_CORRUPT", "ARTIFACT_MISSING")
    assert not (tmp_path / "bad-export").exists()


def test_history_uses_content_addresses_after_project_move(project_dir, tmp_path):
    artifact_analysis(project_dir)
    built = Engine(project_dir).build(trusted=True)
    relocated = tmp_path / "relocated"
    shutil.copytree(project_dir / ".closure", relocated / ".closure")
    store = EvidenceStore(project_dir)
    for value in built["analyses"][0]["record"]["outputs"].values():
        if value["type"] == "artifact":
            store.artifact_path(value).unlink()
    exported = export_report(relocated, tmp_path / "relocated-export", built["id"])
    assert exported["artifacts"] == 1
    manifest = json.loads((tmp_path / "relocated-export/artifacts.json").read_text())
    for artifact in manifest["artifacts"]:
        assert file_digest(tmp_path / "relocated-export" / artifact["file"]) == artifact["sha256"]


def test_legacy_reports_and_invalid_history_ids_are_explicit(project_dir):
    store = EvidenceStore(project_dir)
    old = {"id": "a" * 32, "gate": True, "schema": "closure-report/0.1"}
    atomic_json(store.root / "reports" / f"{old['id']}.json", old)
    assert store.history()["reports"][0]["error"]["code"] == "REPORT_UNSEALED"
    for identifier in ("../../project", "", "not-a-report"):
        with pytest.raises(ClosureError) as exc:
            store.load_report(identifier)
        assert exc.value.code == "HISTORY_ID"


def test_consumed_input_artifacts_are_retained_and_checked(project_dir, tmp_path):
    design = project_dir / "drawing.step"
    design.write_bytes(b"original source CAD")
    edit_yaml(project_dir / "model/payload.yaml", lambda d: (
        d["parameters"].update(design={"type": "artifact", "path": "drawing.step"}),
        d["exports"].append("design")))
    edit_yaml(project_dir / "model/power.yaml", lambda d: d["analyses"]["budget"]["inputs"].update(design={"ref": "payload.design"}))
    artifact_analysis(project_dir)
    report = Engine(project_dir).build(trusted=True)
    assert report["gate"]
    design.unlink()
    store = EvidenceStore(project_dir)
    saved = store.load_report(report["id"])
    original = store.artifact_path(saved["values"]["payload.design"])
    assert original.read_bytes() == b"original source CAD"
    export_report(project_dir, tmp_path / "with-input", report["id"])
    manifest = json.loads((tmp_path / "with-input/artifacts.json").read_text())
    archived_input = next(a for a in manifest["artifacts"] if a["role"] == "input")
    assert (tmp_path / "with-input" / archived_input["file"]).read_bytes() == b"original source CAD"
    original.write_bytes(b"changed")
    with pytest.raises(ClosureError, match="bytes do not match"):
        store.load_report(report["id"])


def test_runner_cannot_change_its_copied_input_and_publish(project_dir):
    (project_dir / "drawing.step").write_text("design")
    edit_yaml(project_dir / "model/payload.yaml", lambda d: (
        d["parameters"].update(design={"type": "artifact", "path": "drawing.step"}),
        d["exports"].append("design")))
    edit_yaml(project_dir / "model/power.yaml", lambda d: d["analyses"]["budget"]["inputs"].update(design={"ref": "payload.design"}))
    runner(project_dir, "pathlib.Path(r['inputs']['design']['path']).write_text('changed')\n"
           "json.dump({'protocol':'closure-run/0.1','invocation_id':r['invocation_id'],'outputs':{'total':{'value':180,'unit':'W'}}},sys.stdout)")
    report = Engine(project_dir).build(trusted=True)
    assert not report["gate"]
    assert report["analyses"][0]["error"]["code"] == "INPUT_MUTATION"
    assert not (project_dir / ".closure/runs").exists()
